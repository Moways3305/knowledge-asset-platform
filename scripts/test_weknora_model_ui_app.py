import tempfile
from pathlib import Path
import unittest

import httpx

from weknora_model_ui_app import SpaFiles


class UiTests(unittest.IsolatedAsyncioTestCase):
    async def test_spa_routes_work_but_missing_assets_and_api_do_not_return_html(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "index.html").write_text("<html>fixture UI</html>")
            from starlette.applications import Starlette
            from starlette.routing import Mount

            app = Starlette(routes=[Mount("/", SpaFiles(directory=directory, html=True))])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://fixture"
            ) as client:
                for path in ("/", "/login", "/admin/weknora-models"):
                    response = await client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("fixture UI", response.text)
                for path in ("/api/missing", "/admin/ops/missing", "/mcp", "/assets/missing.js"):
                    self.assertEqual((await client.get(path)).status_code, 404)
                self.assertEqual((await client.post("/login")).status_code, 405)
