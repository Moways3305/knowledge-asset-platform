"""Local personal-data recognition. Results contain types and offsets, never source values.

Conservative contextual patterns are not general-purpose NER. Original-access checks remain
mandatory; an empty result is not proof that arbitrary text contains no personal data.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import overload

# Bounded recognizers permit safe forward overlap across document windows.
PERSONAL_LOOKAHEAD = 512
PERSONAL_FIELD_KEYS = frozenset(
    {
        "email",
        "phone",
        "phonenumber",
        "mobile",
        "mobilephone",
        "address",
        "homeaddress",
        "fullname",
        "name",
        "patientname",
        "medicalhistory",
        "birthdate",
        "dateofbirth",
        "idcard",
        "bankcard",
        "bankaccount",
        "biometrictemplate",
        "passportnumber",
        "personalsalary",
        "姓名",
        "身份证号",
        "家庭住址",
        "住址",
        "手机号",
        "电话号码",
        "邮箱",
        "诊断结果",
        "病历号",
        "指纹模板",
        "出生日期",
        "个人收入",
        "个人薪资",
        "个人银行账户",
        "护照号码",
        "社保号码",
    }
)


def is_personal_field(key):
    return re.sub(r"[_\-\s]", "", str(key)).lower() in PERSONAL_FIELD_KEYS


@dataclass(frozen=True)
class PersonalMatch:
    category: str
    start: int
    end: int


_CONTACT_RE = re.compile(
    r"(?P<label>客户联系人|项目联系人|联系人|对接人|姓名|受访者|受访人|访谈对象|负责人)"
    r"(?P<sep>[\s:：]+)"
    r"(?P<val>[^\s，,。；;、:：\n]{1,20})"
)

_PERSON_CONTEXT_RES = (
    re.compile(
        r"(?P<label>董事长|总经理|副总经理|财务总监|总监|经理|顾问|受访者|负责人)"
        r"\s*(?!负责|表示|指出|认为|提出|介绍|需要|要求|应当|必须)"
        r"(?P<val>[\u4e00-\u9fff]{2,4}?)(?=表示|指出|认为|提出|介绍|负责|[，,。；;：:\s]|$)"
    ),
    re.compile(r"(?<![\u4e00-\u9fff])(?P<val>[\u4e00-\u9fff]{2,4})(?P<label>先生|女士)"),
)


_SIMPLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 邮箱
    ("email", re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,63}")),
    # 身份证号（18 位：17 数字 + 校验位 0-9/X；或 15 位）。先于银行卡 / 手机号。
    ("id_card", re.compile(r"(?<![0-9Xx])(?:\d{17}[0-9Xx]|\d{15})(?![0-9Xx])")),
    # 银行卡号 / 长账号（16-19 连续数字）。先于手机号。
    ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    # 中国大陆手机号（11 位，1[3-9] 开头）。
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    # 固话（区号 + 号码，可带分隔符）。
    ("landline", re.compile(r"(?<!\d)0\d{2,3}[\-\s]?\d{7,8}(?!\d)")),
    # 其余长数字账号（12-19 位，前面规则未覆盖到的）。
    ("account", re.compile(r"(?<!\d)\d{12,19}(?!\d)")),
)


# Values of explicitly personal fields; do not infer medical conditions from generic text.
_PERSONAL_FIELDS = (
    ("address", r"家庭住址|居住地址|家庭地址|现住址|户籍地址|精确位置|home_address"),
    ("health", r"诊断结果|患者病史|病历号|个人健康状况|medical_history"),
    ("biometric", r"指纹模板|人脸特征|虹膜特征|声纹特征|biometric_template"),
    ("personal_id", r"护照号(?:码)?|社保号(?:码)?|驾驶证号(?:码)?|微信号|出生日期|passport_number"),
    ("personal_finance", r"个人收入|个人薪资|个人工资|个人银行账户|personal_salary"),
    ("phone", r"联系电话|手机号码|电话号码|mobile_phone|phone_number"),
    ("contact", r"个人姓名|真实姓名|full_name|patient_name"),
)
_FIELD_RULES = tuple(
    (
        category,
        re.compile(
            r"(?:" + labels + r")[\"'\s]*[:：=][\s\"']*(?P<val>[^\n\r，,。；;\"'<>]{1,200})", re.I
        ),
    )
    for category, labels in _PERSONAL_FIELDS
)
_FORMATTED_IDENTIFIERS = (
    ("id_card", re.compile(r"(?<![0-9])(?:[0-9][ -]?){17}[0-9Xx](?![0-9])")),
    ("bank_card", re.compile(r"(?<![0-9])(?:[0-9][ -]?){15,18}[0-9](?![0-9])")),
    ("phone", re.compile(r"(?<![0-9])(?:\+?86[ -]?)?1[3-9](?:[ -]?[0-9]){9}(?![0-9])")),
)


def personal_information_matches(text: str) -> list[PersonalMatch]:
    # Match normalized full-width/zero-width forms while preserving original offsets.
    chars, positions = [], []
    for index, char in enumerate(text):
        if unicodedata.category(char) == "Cf":
            continue
        for normalized in unicodedata.normalize("NFKC", char):
            chars.append(normalized)
            positions.append(index)
    normalized = "".join(chars)
    uuid_ranges = [
        match.span()
        for match in re.finditer(
            r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", normalized
        )
    ]
    candidates = []
    rules = (
        *_FIELD_RULES,
        *(("contact", r) for r in (_CONTACT_RE, *_PERSON_CONTEXT_RES)),
        *_SIMPLE_RULES,
        *_FORMATTED_IDENTIFIERS,
    )
    for category, pattern in rules:
        for match in pattern.finditer(normalized):
            start, end = match.span("val") if "val" in match.groupdict() else match.span()
            if any(left <= start and end <= right for left, right in uuid_ranges):
                continue
            value = normalized[start:end].strip()
            if (
                not value
                or value in {"无", "未填写", "待补充", "不适用"}
                or re.fullmatch(r"(?:【[^】]{1,40}】|[＊*]+)", value)
            ):
                continue
            candidates.append(PersonalMatch(category, positions[start], positions[end - 1] + 1))
    # Select the widest enclosing match, preventing a phone/card from being counted twice.
    candidates.sort(key=lambda hit: (hit.start, -(hit.end - hit.start)))
    selected: list[PersonalMatch] = []
    for hit in candidates:
        if selected and hit.start < selected[-1].end:
            previous = selected[-1]
            if hit.end > previous.end:
                selected[-1] = PersonalMatch(previous.category, previous.start, hit.end)
        else:
            selected.append(hit)
    return selected


@overload
def redact_personal_information(text: str, *, preserve_offsets: bool = False) -> str: ...


@overload
def redact_personal_information(text: None, *, preserve_offsets: bool = False) -> None: ...


def redact_personal_information(text: str | None, *, preserve_offsets: bool = False) -> str | None:
    if not text:
        return text
    try:
        result: list[str] = []
        cursor = 0
        for hit in personal_information_matches(text):
            replacement = "＊" * (hit.end - hit.start) if preserve_offsets else "【个人信息已隐藏】"
            result.extend((text[cursor : hit.start], replacement))
            cursor = hit.end
        result.append(text[cursor:])
        return "".join(result)
    except Exception:
        # Never return source text when sanitization fails.
        return "【内容暂不可展示】"


def redact_personal_data(value):
    """Sanitize JSON-shaped evidence/reasons without exposing matches or object reprs."""
    if isinstance(value, str):
        if re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
            return value
        return redact_personal_information(value)
    if isinstance(value, dict):
        return {
            redact_personal_information(str(k)): redact_personal_data(v) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_personal_data(v) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "【内容暂不可展示】"
