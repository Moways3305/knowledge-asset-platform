"""Docker runtime preservation and cold copies for the explicitly authorized KAP cutover.

Original containers and verified cold copies are retained. Automatic recovery is
permitted only before the durable traffic-opening boundary. No volumes are deleted.
"""

import copy
import hashlib
import os
import re
import shutil
import http.client
import json
from pathlib import Path
import socket
from urllib.parse import quote

from prepare_production_release import require

LABEL = "kap.production.cutover"
OPERATIONAL_DIRECTORIES = {Path("/data/weknora/repo"), Path("/data/weknora/releases/v0.7.1")}


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


class Engine:
    def __init__(self, log):
        self.log = log
        self.version = ""
        version = self.request("GET", "/version")["ApiVersion"]
        require(tuple(map(int, version.split("."))) >= (1, 44), "Docker API version too old")
        self.version = "/v" + version

    def request(self, method, path, body=None):
        connection = UnixConnection("localhost", timeout=90)
        try:
            data = None if body is None else json.dumps(body).encode()
            connection.request(
                method, self.version + path, body=data, headers={"Content-Type": "application/json"}
            )
            response = connection.getresponse()
            raw = response.read()
            if response.status >= 400:
                self.log.write(raw)
                self.log.flush()
                raise RuntimeError("Docker operation failed; private details retained")
            return json.loads(raw) if raw else None
        finally:
            connection.close()


def endpoints(item):
    return {
        name: {
            k: copy.deepcopy(value[k])
            for k in ("Aliases", "IPAMConfig", "DriverOpts")
            if value.get(k) is not None
        }
        for name, value in item["NetworkSettings"]["Networks"].items()
    }


def payload(original, image, image_config, old_image_config, token, *, publish=False):
    config = copy.deepcopy(original["Config"])
    # Preserve operator overrides; adopt new image defaults only where the old
    # runtime used the corresponding old image default.
    for key in ("Cmd", "Entrypoint", "User", "WorkingDir", "Healthcheck", "StopSignal"):
        if config.get(key) == old_image_config.get(key):
            if key in image_config:
                config[key] = copy.deepcopy(image_config[key])
            else:
                config.pop(key, None)
    config["Image"] = image
    config["Labels"] = {**(config.get("Labels") or {}), LABEL: token}
    env = dict(line.split("=", 1) for line in image_config.get("Env", []) if "=" in line)
    env.update(line.split("=", 1) for line in original["Config"].get("Env", []) if "=" in line)
    if original["Name"] == "/WeKnora-app":
        env["AUTO_MIGRATE"] = "false"
    config["Env"] = [key + "=" + value for key, value in env.items()]
    host = copy.deepcopy(original["HostConfig"])
    require(
        not host.get("AutoRemove")
        and not host.get("Privileged")
        and not host.get("VolumesFrom")
        and not host.get("Links")
        and not host.get("ContainerIDFile"),
        "unsupported runtime configuration",
    )
    require(
        host.get("NetworkMode") not in {"host", "none"}
        and not host.get("NetworkMode", "").startswith("container:"),
        "unsupported production network",
    )
    host.pop("Binds", None)
    host["Mounts"] = []
    for mount in original.get("Mounts", []):
        require(mount["Type"] in {"volume", "bind"}, "unsupported production mount")
        entry = {
            "Type": mount["Type"],
            "Source": mount.get("Name") if mount["Type"] == "volume" else mount["Source"],
            "Target": mount["Destination"],
            "ReadOnly": not mount["RW"],
        }
        if mount["Type"] == "volume":
            entry["VolumeOptions"] = {"NoCopy": True}
        elif mount.get("Propagation"):
            entry["BindOptions"] = {"Propagation": mount["Propagation"]}
        host["Mounts"].append(entry)
    host["RestartPolicy"] = (
        copy.deepcopy(original["HostConfig"]["RestartPolicy"])
        if publish
        else {"Name": "no", "MaximumRetryCount": 0}
    )
    host["PublishAllPorts"] = False
    if not publish:
        host["PortBindings"] = {}
    config["HostConfig"] = host
    config["NetworkingConfig"] = {"EndpointsConfig": endpoints(original)}
    return config


# The helper has only the two declared mounts. Compare contents, numeric ownership,
# mode bits and symlink targets; paths/hashes stay in private evidence.
VERIFY_COPY = r"""
import hashlib, os, stat

def manifest(root):
    result = {}
    def walk(path, key):
        info = os.lstat(path)
        mode = stat.S_IFMT(info.st_mode)
        value = [mode, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid]
        if stat.S_ISLNK(info.st_mode):
            value.append(os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            digest = hashlib.sha256()
            with open(path, 'rb') as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(chunk)
            value += [info.st_size, digest.hexdigest()]
        elif not stat.S_ISDIR(info.st_mode):
            raise RuntimeError('unsupported file type')
        result[key] = value
        if stat.S_ISDIR(info.st_mode):
            for name in sorted(os.listdir(path)):
                walk(os.path.join(path, name), key + '/' + name)
    walk(root, '')
    return result
assert manifest('/from') == manifest('/to/object'), 'cold copy differs'
"""


class Runtime:
    def __init__(self, runner, engine, directory, originals, helper_image):
        self.r, self.api, self.directory = runner, engine, directory
        self.token = directory.name
        self.helper_image = helper_image
        self.state = {
            "originals": originals,
            "backups": [],
            "config_replacements": [],
            "tag_replacements": [],
            "new": {},
            "helpers": [],
            "renamed": [],
            "backup_complete": False,
            "data_mutated": False,
            "traffic_opening": False,
            "recovery_opening": False,
            "touched": False,
            "passed": False,
        }
        self.save()

    def save(self):
        path = self.directory / "state-private.json"
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.state, stream)
            stream.flush()
            import os

            os.fsync(stream.fileno())
        temporary.replace(path)
        import os

        fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def owned(self, identity):
        item = self.r.inspect(identity)
        require(
            item["Config"].get("Labels", {}).get(LABEL) == self.token,
            "cutover resource identity mismatch",
        )
        return item

    def helper(self, command, mounts=(), *, image=None, network="none", env=()):
        name = "kap-cutover-helper-" + self.token[-10:] + "-" + str(len(self.state["helpers"]))
        args = [
            "create",
            "--name",
            name,
            "--label",
            LABEL + "=" + self.token,
            "--label",
            "com.docker.compose.project=kap-cutover-helper",
            "--restart",
            "no",
            "--network",
            network,
            "--user",
            "0:0",
            "--entrypoint",
            command[0],
        ]
        for mount in mounts:
            args += ["--mount", mount]
        if env:
            require(
                all("\n" not in value and "\r" not in value for value in env),
                "multiline environment unsupported",
            )
            path = self.directory / (name + "-private.env")
            path.write_text("\n".join(env) + "\n")
            path.chmod(0o600)
            args += ["--env-file", str(path)]
        identity = self.r.docker(*args, image or self.helper_image, *command[1:])
        self.state["helpers"].append(identity)
        self.save()
        try:
            self.r.execute(["docker", "start", "-a", identity], timeout=1800)
            item = self.owned(identity)
            require(
                not item["State"]["Running"] and item["State"]["ExitCode"] == 0,
                "cutover helper failed",
            )
        finally:
            item = self.owned(identity)
            if item["State"]["Running"]:
                self.r.docker("stop", "-t", "30", identity)

    def freeze(self, order):
        self.state["touched"] = True
        self.save()
        for name in order:
            item = self.state["originals"][name]
            current = self.r.inspect(item["Id"])
            require(current["Image"] == item["Image"], "original image changed")
            self.r.docker("update", "--restart=no", item["Id"])
            self.r.docker("stop", "-t", "600", item["Id"], timeout=660)
            stopped = self.r.inspect(item["Id"])
            require(
                not stopped["State"]["Running"] and stopped["State"].get("ExitCode") != 137,
                "service did not stop cleanly",
            )

    def backup(self, stores):
        require(
            all(
                not self.r.inspect(item["Id"])["State"]["Running"]
                for name, item in self.state["originals"].items()
                if name != "kap-migrate-1"
            ),
            "writers still running",
        )
        for index, store in enumerate(stores):
            mount = store["mount"]
            require(mount["Type"] in {"volume", "bind"}, "unsupported cold backup")
            source = mount["Name"] if mount["Type"] == "volume" else mount["Source"]
            require("," not in source, "unsupported mount path")
            volume = "kap-cold-" + self.token[-10:] + "-" + str(index)
            require(
                not self.r.docker("volume", "ls", "-q", "--filter", "name=^" + volume + "$"),
                "backup volume already exists",
            )
            self.r.docker("volume", "create", "--label", LABEL + "=" + self.token, volume)
            entry = {"mount": mount, "volume": volume, "verified": False}
            self.state["backups"].append(entry)
            self.save()
            mounts = [
                f"type={mount['Type']},src={source},dst=/from,readonly",
                f"type=volume,src={volume},dst=/to",
            ]
            print(f"制作并校验停写副本 {index + 1}/{len(stores)}。", flush=True)
            self.helper(
                ["sh", "-ec", "test ! -e /to/object; cp -a /from /to/object; sync -f /to"], mounts
            )
            self.helper(["python", "-c", VERIFY_COPY], mounts)
            entry["verified"] = True
            self.save()
        self.state["backup_complete"] = True
        self.save()

    def detach_originals(self):
        for name, item in self.state["originals"].items():
            if name == "kap-migrate-1":
                continue
            require(not self.r.inspect(item["Id"])["State"]["Running"], "original still running")
            self.state["renamed"].append(name)
            self.save()
            for network in endpoints(item):
                if network in self.r.inspect(item["Id"])["NetworkSettings"]["Networks"]:
                    self.api.request(
                        "POST",
                        "/networks/" + quote(network, safe="") + "/disconnect",
                        {"Container": item["Id"], "Force": False},
                    )
            self.r.docker("rename", item["Id"], name + "-previous-" + self.token[-10:])

    def create(self, name, config):
        require(config["Labels"].get(LABEL) == self.token, "new container missing identity")
        identity = self.api.request(
            "POST", "/containers/create?name=" + quote(name, safe=""), config
        )["Id"]
        self.state["new"][name] = identity
        self.save()
        return identity

    def start(self, name):
        self.r.docker("start", self.state["new"][name])

    def remove_new(self, name):
        identity = self.state["new"][name]
        item = self.owned(identity)
        if item["State"]["Running"]:
            self.r.docker("stop", "-t", "120", identity, timeout=150)
        self.r.docker("rm", identity)  # Never -v.
        del self.state["new"][name]
        self.save()

    def configure_entrypoints(self, paths, managed_weknora, images):
        for index, target in enumerate(paths):
            target = Path(target)
            require(
                target.parent in OPERATIONAL_DIRECTORIES and target.name == "docker-compose.yml",
                "unexpected operational config target",
            )
            backup = self.directory / f"operational-config-before-{index}-private"
            shutil.copyfile(target, backup)
            backup.chmod(0o600)
            record = {
                "target": str(target),
                "backup": str(backup),
                "mode": target.stat().st_mode & 0o777,
                "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
            }
            self.state["config_replacements"].append(record)
            self.save()
            temporary = target.with_name(target.name + "." + self.token + ".tmp")
            shutil.copyfile(managed_weknora, temporary)
            temporary.chmod(0o600)
            with temporary.open("rb+") as stream:
                os.fsync(stream.fileno())
            temporary.replace(target)
        for service, image in images.items():
            require(
                service in {"backend", "worker", "ocr_worker", "beat", "frontend", "migrate"},
                "unexpected operational image",
            )
            tag = "kap-" + service + ":latest"
            old = self.r.image_identity(tag)
            self.state["tag_replacements"].append({"tag": tag, "old": old, "new": image})
            self.save()
            self.r.docker("tag", image, tag)
            require(self.r.image_identity(tag) == image, "operational image tag changed")

    def restore_entrypoints(self):
        for entry in self.state.get("config_replacements", []):
            target, backup = Path(entry["target"]), Path(entry["backup"])
            require(
                target.parent in OPERATIONAL_DIRECTORIES and target.name == "docker-compose.yml",
                "unexpected operational config target",
            )
            require(
                backup.resolve().parent == self.directory
                and hashlib.sha256(backup.read_bytes()).hexdigest() == entry["sha256"],
                "operational config backup changed",
            )
            temporary = target.with_name(target.name + "." + self.token + ".tmp")
            shutil.copyfile(backup, temporary)
            temporary.chmod(entry["mode"])
            temporary.replace(target)
        for entry in self.state.get("tag_replacements", []):
            require(
                re.fullmatch(
                    r"kap-(backend|worker|ocr_worker|beat|frontend|migrate):latest", entry["tag"]
                ),
                "unexpected operational tag",
            )
            current = self.r.image_identity(entry["tag"])
            require(current in {entry["old"], entry["new"]}, "operational tag concurrently changed")
            if entry["old"]:
                self.r.docker("tag", entry["old"], entry["tag"])
            elif current:
                self.r.docker("image", "rm", entry["tag"])

    def recover(self, start_order):
        require(
            not self.state["traffic_opening"],
            "traffic boundary crossed; automatic data rollback forbidden",
        )
        if not self.state["touched"]:
            return
        if self.state.get("recovery_opening"):
            # A previous recovery may already have accepted writes through the
            # old release. Resume starts only; never restore that snapshot again.
            for name in start_order:
                old = self.state["originals"][name]
                item = self.r.inspect(old["Id"])
                require(
                    item["Name"] == "/" + name
                    and item["Image"] == old["Image"]
                    and item["Config"] == old["Config"],
                    "recovery runtime identity changed",
                )
                if not item["State"]["Running"]:
                    self.r.docker("start", old["Id"])
            self.state["recovered"] = True
            self.save()
            return
        # Discover labelled resources too, covering a crash after create but before save.
        ids = self.r.docker(
            "ps", "-aq", "--filter", "label=" + LABEL + "=" + self.token
        ).splitlines()
        for identity in ids:
            item = self.owned(identity)
            if item["State"]["Running"]:
                self.r.docker("stop", "-t", "120", identity, timeout=150)
            if item["Name"].lstrip("/") in self.state["originals"]:
                self.r.docker("rm", identity)
        for old in self.state["originals"].values() if self.state["data_mutated"] else []:
            require(
                not self.r.inspect(old["Id"])["State"]["Running"], "original restarted unexpectedly"
            )
        if self.state["data_mutated"]:
            require(
                self.state["backup_complete"] and all(x["verified"] for x in self.state["backups"]),
                "no complete verified cold copy",
            )
            for entry in self.state["backups"]:
                volume = json.loads(self.r.docker("volume", "inspect", entry["volume"]))[0]
                require(
                    volume.get("Labels", {}).get(LABEL) == self.token, "backup identity changed"
                )
                mount = entry["mount"]
                source = mount["Name"] if mount["Type"] == "volume" else mount["Source"]
                # Explicitly mounted destination only; no host-wide filesystem commands.
                self.helper(
                    [
                        "sh",
                        "-ec",
                        "if [ -d /from/object ]; then find /to -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; cp -a /from/object/. /to/; else cp -p /from/object /to; fi; sync -f /to",
                    ],
                    [
                        f"type=volume,src={entry['volume']},dst=/from,readonly",
                        f"type={mount['Type']},src={source},dst=/to",
                    ],
                )
                self.helper(
                    ["python", "-c", VERIFY_COPY],
                    [
                        f"type={mount['Type']},src={source},dst=/from,readonly",
                        f"type=volume,src={entry['volume']},dst=/to,readonly",
                    ],
                )
        self.restore_entrypoints()
        for name, old in self.state["originals"].items():
            if name == "kap-migrate-1":
                continue
            current = self.r.inspect(old["Id"])
            if current["Name"] != "/" + name:
                self.r.docker("rename", old["Id"], name)
            for network, endpoint in endpoints(old).items():
                if network not in self.r.inspect(old["Id"])["NetworkSettings"]["Networks"]:
                    self.api.request(
                        "POST",
                        "/networks/" + quote(network, safe="") + "/connect",
                        {"Container": old["Id"], "EndpointConfig": endpoint},
                    )
            policy = old["HostConfig"]["RestartPolicy"]
            self.api.request(
                "POST", "/containers/" + old["Id"] + "/update", {"RestartPolicy": policy}
            )
        self.state["recovery_opening"] = True
        self.save()
        for name in start_order:
            self.r.docker("start", self.state["originals"][name]["Id"])
        self.state["recovered"] = True
        self.save()
