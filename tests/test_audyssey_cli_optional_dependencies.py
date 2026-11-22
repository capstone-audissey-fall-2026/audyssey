import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


BLOCK_LLM_SDKS = """\
import importlib.abc
import sys

class BlockLLMSDKs(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.')
               for name in ('google.genai', 'openai')):
            raise ModuleNotFoundError('LLM SDK is not installed: ' + fullname)

sys.meta_path.insert(0, BlockLLMSDKs())
"""


class CliOptionalDependenciesTests(unittest.TestCase):
    def run_without_llm_sdks(self, script):
        environment = os.environ.copy()
        environment["LANGSMITH_TRACING"] = "false"
        result = subprocess.run(
            [sys.executable, "-c", BLOCK_LLM_SDKS + textwrap.dedent(script)],
            cwd=Path(__file__).resolve().parent.parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_command_help_without_llm_sdks(self):
        self.run_without_llm_sdks("""
            from audyssey.cli import app
            from typer.testing import CliRunner
            for args in (
                ['--help'], ['serve', '--help'], ['tool-server', '--help'],
                ['eval-routing', '--help'], ['improve-routing', '--help'],
            ):
                result = CliRunner().invoke(app, args)
                assert result.exit_code == 0, (args, result.output, result.exception)
        """)

    def test_real_tool_server_starts_without_llm_sdks(self):
        self.run_without_llm_sdks("""
            from audyssey.cli import app
            from fastapi.testclient import TestClient
            from typer.testing import CliRunner
            from unittest.mock import patch
            tools = ['separation', 'filtering', 'grounding', 'generation']
            args = ['tool-server', '--impl', 'real']
            for tool in tools:
                args.extend(['--tool', tool])
            with patch('audyssey.cli.uvicorn.run') as run:
                result = CliRunner().invoke(app, args)
                assert result.exit_code == 0, (result.output, result.exception)
                run.assert_called_once()
                with TestClient(run.call_args.args[0]) as client:
                    response = client.get('/health')
                    assert response.status_code == 200, response.text
                    assert response.json() == {'tools': tools, 'impl': 'real'}
        """)
