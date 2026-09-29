# 第三方依赖与许可清单

整理日期：2026-09-16。本地清单依据项目锁文件、构建配置，以及已检查测试环境中安装发行包的 `dist-info/METADATA` 和许可证文件。补充官方来源声明见 [PROVIDER-TERMS.md](PROVIDER-TERMS.md)：已读取 uvloop、httpx2-jsfetch 的版本许可声明、Hatch 上游许可及数据来源条款。保留本地证据和网页证据的区别，没有安装新依赖，也没有替第一方项目选择或授予许可证。

## 范围与本地证据

项目：Life Exchange Rate MCP 0.2.0。根运行时声明为 `fastapi`、`httpx`、`mcp[cli]`、`pydantic`、`uvicorn[standard]`；开发额外依赖为 `pytest` 与 `pytest-asyncio`。所有第三方锁定条目的注册源均为 `https://pypi.org/simple`；具体构件 URL 与哈希保留在 `source/uv.lock`。

- 锁文件：`source/uv.lock`。SHA-256：`d67c058ded87d2778474f63fe051214025122c77982f80baf1e7bee1c94a4e5d`。
- 项目配置：`source/pyproject.toml`。
- 表格“本地元数据”路径以已检查测试环境的 `site-packages/` 为相对根目录；不包含个人机器路径。
- [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) 汇总实际读到的 68 份许可、版权或作者文本。每份均保留原相对路径标题、SHA-256、原文长度及完整原始字节；没有生成或替换上游许可。原文不能因表内简写而被忽略。

本表按锁文件依赖边和启用的 extras 计算传递闭包，列出 **48 个运行时第三方锁定发行包**，包括平台条件依赖；另有 **5 个仅开发依赖**。它是支持平台的联合清单，不表示这些包全部同时安装在 Vercel Linux 或本地 Windows。元数据仅在本地安装版本与锁定版本完全一致时用于许可证明。

上游 Python 依赖通过正常依赖安装取得；它们的实现源码、虚拟环境及 wheel 并未随项目源码复制。本次审阅附带的是读取到的许可/通知文本。依赖声明不等于代替上游授予权利，本清单也未审计所有 wheel 内嵌的原生库或平台运行时。

## 锁定运行时依赖

“直接”表示来自根项目运行时声明；其余为传递依赖。许可名称按实际元数据记录保留，没有将旧式名称强行换成未经确认的 SPDX 标识。

| 包 | 锁定版本 | 来源层级/条件 | 本地许可记录 | 本地元数据 | 原文副本 |
|---|---|---|---|---|---|
| annotated-doc | 0.0.5 | 传递 | MIT | `annotated_doc-0.0.5.dist-info/METADATA`（License-Expression） | [dependency-notices/annotated_doc-0.0.5.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| annotated-types | 0.8.0 | 传递 | MIT | `annotated_types-0.8.0.dist-info/METADATA`（License-Expression） | [dependency-notices/annotated_types-0.8.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| anyio | 4.15.1 | 传递 | MIT | `anyio-4.15.1.dist-info/METADATA`（License-Expression） | [dependency-notices/anyio-4.15.1.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| attrs | 26.1.0 | 传递 | MIT | `attrs-26.1.0.dist-info/METADATA`（License-Expression） | [dependency-notices/attrs-26.1.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| certifi | 2026.7.22 | 传递 | MPL-2.0 | `certifi-2026.7.22.dist-info/METADATA`（License） | [dependency-notices/certifi-2026.7.22.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| cffi | 2.1.1 | 传递 | MIT-0 | `cffi-2.1.1.dist-info/METADATA`（License-Expression） | [dependency-notices/cffi-2.1.1.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| click | 8.5.0 | 传递 | BSD-3-Clause | `click-8.5.0.dist-info/METADATA`（License-Expression） | [dependency-notices/click-8.5.0.dist-info/licenses/LICENSE.txt](THIRD_PARTY_NOTICES.txt) |
| colorama | 0.4.6 | 传递；Windows 条件 | BSD License（分类器）；许可原文含三项条件 | `colorama-0.4.6.dist-info/METADATA`（Classifier + LICENSE.txt） | [dependency-notices/colorama-0.4.6.dist-info/licenses/LICENSE.txt](THIRD_PARTY_NOTICES.txt) |
| cryptography | 50.0.1 | 传递 | Apache-2.0 OR BSD-3-Clause | `cryptography-50.0.1.dist-info/METADATA`（License-Expression） | [dependency-notices/cryptography-50.0.1.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/cryptography-50.0.1.dist-info/licenses/LICENSE.APACHE](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/cryptography-50.0.1.dist-info/licenses/LICENSE.BSD](THIRD_PARTY_NOTICES.txt) |
| fastapi | 0.141.1 | 直接 | MIT | `fastapi-0.141.1.dist-info/METADATA`（License-Expression） | [dependency-notices/fastapi-0.141.1.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| h11 | 0.16.0 | 传递 | MIT | `h11-0.16.0.dist-info/METADATA`（License） | [dependency-notices/h11-0.16.0.dist-info/licenses/LICENSE.txt](THIRD_PARTY_NOTICES.txt) |
| httpcore | 1.0.9 | 传递 | BSD-3-Clause | `httpcore-1.0.9.dist-info/METADATA`（License-Expression） | [dependency-notices/httpcore-1.0.9.dist-info/licenses/LICENSE.md](THIRD_PARTY_NOTICES.txt) |
| httpcore2 | 2.12.0 | 传递 | BSD-3-Clause | `httpcore2-2.12.0.dist-info/METADATA`（License-Expression） | [dependency-notices/httpcore2-2.12.0.dist-info/licenses/LICENSE.md](THIRD_PARTY_NOTICES.txt) |
| httptools | 0.8.0 | 传递 | MIT | `httptools-0.8.0.dist-info/METADATA`（License-Expression） | [dependency-notices/httptools-0.8.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/httptools-0.8.0.dist-info/licenses/vendor/http-parser/LICENSE-MIT](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/httptools-0.8.0.dist-info/licenses/vendor/llhttp/LICENSE](THIRD_PARTY_NOTICES.txt) |
| httpx | 0.28.1 | 直接 | BSD-3-Clause | `httpx-0.28.1.dist-info/METADATA`（License） | [dependency-notices/httpx-0.28.1.dist-info/licenses/LICENSE.md](THIRD_PARTY_NOTICES.txt) |
| httpx2 | 2.12.0 | 传递 | BSD-3-Clause | `httpx2-2.12.0.dist-info/METADATA`（License-Expression） | [dependency-notices/httpx2-2.12.0.dist-info/licenses/LICENSE.md](THIRD_PARTY_NOTICES.txt) |
| httpx2-jsfetch | 1.0 | 传递；Python ≥3.12 且 Emscripten | 本地无该版本元数据/原文；上游发布页声明见 [PROVIDER-TERMS.md](PROVIDER-TERMS.md) | 未找到匹配版本 | — |
| idna | 3.19 | 传递 | BSD-3-Clause | `idna-3.19.dist-info/METADATA`（License-Expression） | [dependency-notices/idna-3.19.dist-info/licenses/LICENSE.md](THIRD_PARTY_NOTICES.txt) |
| jsonschema | 4.26.0 | 传递 | MIT | `jsonschema-4.26.0.dist-info/METADATA`（License-Expression） | [dependency-notices/jsonschema-4.26.0.dist-info/licenses/COPYING](THIRD_PARTY_NOTICES.txt) |
| jsonschema-specifications | 2025.9.1 | 传递 | MIT | `jsonschema_specifications-2025.9.1.dist-info/METADATA`（License-Expression） | [dependency-notices/jsonschema_specifications-2025.9.1.dist-info/licenses/COPYING](THIRD_PARTY_NOTICES.txt) |
| markdown-it-py | 4.2.0 | 传递 | MIT License | `markdown_it_py-4.2.0.dist-info/METADATA`（Classifier） | [dependency-notices/markdown_it_py-4.2.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/markdown_it_py-4.2.0.dist-info/licenses/LICENSE.markdown-it](THIRD_PARTY_NOTICES.txt) |
| mcp | 2.2.0 | 直接 | MIT | `mcp-2.2.0.dist-info/METADATA`（License） | [dependency-notices/mcp-2.2.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| mcp-types | 2.2.0 | 传递 | MIT | `mcp_types-2.2.0.dist-info/METADATA`（License） | [dependency-notices/mcp_types-2.2.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| mdurl | 0.1.2 | 传递 | MIT License | `mdurl-0.1.2.dist-info/METADATA`（Classifier） | [dependency-notices/mdurl-0.1.2.dist-info/LICENSE](THIRD_PARTY_NOTICES.txt) |
| opentelemetry-api | 1.44.0 | 传递 | Apache-2.0 | `opentelemetry_api-1.44.0.dist-info/METADATA`（License-Expression） | [dependency-notices/opentelemetry_api-1.44.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| pycparser | 3.0 | 传递 | BSD-3-Clause | `pycparser-3.0.dist-info/METADATA`（License-Expression） | [dependency-notices/pycparser-3.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| pydantic | 2.13.5 | 直接 | MIT | `pydantic-2.13.5.dist-info/METADATA`（License-Expression） | [dependency-notices/pydantic-2.13.5.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| pydantic-core | 2.46.5 | 传递 | MIT | `pydantic_core-2.46.5.dist-info/METADATA`（License-Expression） | [dependency-notices/pydantic_core-2.46.5.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| pygments | 2.21.0 | 传递 | BSD-2-Clause | `pygments-2.21.0.dist-info/METADATA`（License-Expression） | [dependency-notices/pygments-2.21.0.dist-info/licenses/AUTHORS](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/pygments-2.21.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| pyjwt | 2.14.0 | 传递 | MIT | `pyjwt-2.14.0.dist-info/METADATA`（License-Expression） | [dependency-notices/pyjwt-2.14.0.dist-info/licenses/AUTHORS.rst](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/pyjwt-2.14.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| python-dotenv | 1.2.3 | 传递 | BSD-3-Clause | `python_dotenv-1.2.3.dist-info/METADATA`（License） | [dependency-notices/python_dotenv-1.2.3.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| python-multipart | 0.0.32 | 传递 | Apache-2.0 | `python_multipart-0.0.32.dist-info/METADATA`（License-Expression） | [dependency-notices/python_multipart-0.0.32.dist-info/licenses/LICENSE.txt](THIRD_PARTY_NOTICES.txt) |
| pywin32 | 312 | 传递；`sys_platform == win32` | PSF（顶层元数据）；含 LGPL v2.1 等组件原文，见下文 | `pywin32-312.dist-info/METADATA`（License + 多个组件许可） | [dependency-notices/pywin32-312.dist-info/licenses/adodbapi/license.txt](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/pywin32-312.dist-info/licenses/com/License.txt](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/pywin32-312.dist-info/licenses/com/win32comext/mapi/src/MAPIStubLibrary/LICENSE](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/pywin32-312.dist-info/licenses/isapi/README.txt](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/pywin32-312.dist-info/licenses/pythonwin/License.txt](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/pywin32-312.dist-info/licenses/pythonwin/pywin/idle/LICENSE.txt](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/pywin32-312.dist-info/licenses/pythonwin/Scintilla/License.txt](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/pywin32-312.dist-info/licenses/win32/License.txt](THIRD_PARTY_NOTICES.txt) |
| pyyaml | 6.0.3 | 传递 | MIT | `pyyaml-6.0.3.dist-info/METADATA`（License） | [dependency-notices/pyyaml-6.0.3.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| referencing | 0.37.0 | 传递 | MIT | `referencing-0.37.0.dist-info/METADATA`（License-Expression） | [dependency-notices/referencing-0.37.0.dist-info/licenses/COPYING](THIRD_PARTY_NOTICES.txt) |
| rich | 15.0.0 | 传递 | MIT | `rich-15.0.0.dist-info/METADATA`（License） | [dependency-notices/rich-15.0.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| rpds-py | 2026.6.3 | 传递 | MIT | `rpds_py-2026.6.3.dist-info/METADATA`（License-Expression） | [dependency-notices/rpds_py-2026.6.3.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| shellingham | 1.5.4 | 传递 | ISC License | `shellingham-1.5.4.dist-info/METADATA`（License） | [dependency-notices/shellingham-1.5.4.dist-info/LICENSE](THIRD_PARTY_NOTICES.txt) |
| sse-starlette | 3.4.11 | 传递 | BSD-3-Clause | `sse_starlette-3.4.11.dist-info/METADATA`（License-Expression） | [dependency-notices/sse_starlette-3.4.11.dist-info/licenses/AUTHORS](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/sse_starlette-3.4.11.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| starlette | 1.6.0 | 传递 | BSD-3-Clause | `starlette-1.6.0.dist-info/METADATA`（License-Expression） | [dependency-notices/starlette-1.6.0.dist-info/licenses/LICENSE.md](THIRD_PARTY_NOTICES.txt) |
| truststore | 0.10.4 | 传递 | MIT | `truststore-0.10.4.dist-info/METADATA`（License-Expression） | [dependency-notices/truststore-0.10.4.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| typer | 0.27.2 | 传递 | MIT | `typer-0.27.2.dist-info/METADATA`（License-Expression） | [dependency-notices/typer-0.27.2.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| typing-extensions | 4.16.0 | 传递 | PSF-2.0 | `typing_extensions-4.16.0.dist-info/METADATA`（License-Expression） | [dependency-notices/typing_extensions-4.16.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| typing-inspection | 0.4.4 | 传递 | MIT | `typing_inspection-0.4.4.dist-info/METADATA`（License-Expression） | [dependency-notices/typing_inspection-0.4.4.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| uvicorn | 0.53.0 | 直接 | BSD-3-Clause | `uvicorn-0.53.0.dist-info/METADATA`（License-Expression） | [dependency-notices/uvicorn-0.53.0.dist-info/licenses/LICENSE.md](THIRD_PARTY_NOTICES.txt) |
| uvloop | 0.22.1 | 传递；非 PyPy、非 Cygwin、非 Windows | 本地无该版本元数据/原文；上游发布页声明见 [PROVIDER-TERMS.md](PROVIDER-TERMS.md) | 未找到匹配版本 | — |
| watchfiles | 1.2.0 | 传递 | MIT | `watchfiles-1.2.0.dist-info/METADATA`（License） | [dependency-notices/watchfiles-1.2.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| websockets | 17.1 | 传递 | BSD-3-Clause | `websockets-17.1.dist-info/METADATA`（License-Expression） | [dependency-notices/websockets-17.1.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |

## 仅开发依赖

下列包仅来自 `dev` 额外依赖。开发与运行时共享的 `colorama`, `pygments`, `typing-extensions` 已在运行时表中列出，不重复计数。

| 包 | 锁定版本 | 来源层级 | 本地许可记录 | 本地元数据 | 原文副本 |
|---|---|---|---|---|---|
| iniconfig | 2.3.0 | 传递 dev | MIT | `iniconfig-2.3.0.dist-info/METADATA`（License-Expression） | [dependency-notices/iniconfig-2.3.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| packaging | 26.3 | 传递 dev | Apache-2.0 OR BSD-2-Clause | `packaging-26.3.dist-info/METADATA`（License-Expression） | [dependency-notices/packaging-26.3.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/packaging-26.3.dist-info/licenses/LICENSE.APACHE](THIRD_PARTY_NOTICES.txt)<br>[dependency-notices/packaging-26.3.dist-info/licenses/LICENSE.BSD](THIRD_PARTY_NOTICES.txt) |
| pluggy | 1.6.0 | 传递 dev | MIT | `pluggy-1.6.0.dist-info/METADATA`（License） | [dependency-notices/pluggy-1.6.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| pytest | 9.1.1 | 直接 dev | MIT | `pytest-9.1.1.dist-info/METADATA`（License-Expression） | [dependency-notices/pytest-9.1.1.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |
| pytest-asyncio | 1.4.0 | 直接 dev | Apache-2.0 | `pytest_asyncio-1.4.0.dist-info/METADATA`（License-Expression） | [dependency-notices/pytest_asyncio-1.4.0.dist-info/licenses/LICENSE](THIRD_PARTY_NOTICES.txt) |

## 构建依赖与未确认项

- `hatchling` 是 `source/pyproject.toml` 声明的构建后端；本锁文件没有锁定其版本，已检查测试环境未安装它。已读取 Hatch 当前上游 MIT 许可，见 [PROVIDER-TERMS.md](PROVIDER-TERMS.md)；实际隔离构建后端版本及其对应构件仍未核实，不把它冒充锁定运行时依赖。
- `uvloop 0.22.1`：锁文件包含非 Windows 条件依赖。本地 Windows 测试环境没有匹配的已安装发行包；其版本发布页声明 MIT/Apache-2.0 双许可，见 [PROVIDER-TERMS.md](PROVIDER-TERMS.md)。尚未核对 Linux 部署安装构件或复制该构件许可原文，因此不能把本地表当作完整的线上许可凭证。
- `httpx2-jsfetch 1.0`：锁文件中的 Emscripten 条件依赖，本地 Windows 测试环境未安装；其版本发布页声明 BSD-3-Clause，见 [PROVIDER-TERMS.md](PROVIDER-TERMS.md)。尚未取得对应安装构件的许可原文。
- 这里只确认锁文件与本地元数据，未读取 Vercel 上的安装目录；线上实际构件、原生组件和构建工具应在需要完整部署软件物料清单时另行核对。

## 多组件许可需要保留原文

`pywin32 312` 的顶层元数据写作 `PSF`，但本地随包许可不能概括为“全部 PSF”：

- `licenses/adodbapi/license.txt` 是 **GNU Lesser General Public License, Version 2.1, February 1999** 的文本。该文件本身不足以确认所有相关组件是否有 “or later” 授权，因此不另行推断 SPDX 后缀。
- `licenses/com/License.txt`、`licenses/pythonwin/License.txt`、`licenses/win32/License.txt` 含各自版权主体、三项再分发条件及免责声明。
- `licenses/com/win32comext/mapi/src/MAPIStubLibrary/LICENSE` 明示 MIT；Scintilla、IDLE/Python 另附自己的许可文本。
- `licenses/isapi/README.txt` 只有本地读取到的版权/介绍文本，不能把它当作完整的独立许可授权。所有这些文件均按原样附上。
- `pywin32` 的锁文件条件为 Windows；本清单没有据此推断它存在于 Vercel Linux 部署。

此外，`httptools` 同时附带 http-parser、llhttp 的许可；`markdown-it-py` 附带 markdown-it 的许可；`cryptography` 与仅开发的 `packaging` 各自附有双许可原文。它们均以原始相对路径标识在汇总文本中保留，不替用户选择双许可分支。

## 数据来源条款：独立于代码依赖许可

[PROVIDER-TERMS.md](PROVIDER-TERMS.md) 记录了 2026-09-16 已读取的 Frankfurter、ECB、Federal Reserve Board、EIA 官方条款及其适用边界。这些声明没有转让上游数据所有权，也不能用 Python 依赖许可代替。保存来源链接、观测日期和对衍生计算的说明，并继续明确标注合成人物、价格及政策/能源样例。

带密钥的 EIA 实时调用尚未完成；公开验证中的能源调用使用合成样例。Vercel Hobby 的计划资格及配额属于托管服务条款，不属于代码或数据许可。第一方许可和参赛授权由提交包中的 `RIGHTS.md` 单独载明；本清单不代签或变更该声明。

## 原文副本核验

已将 **68 个**实际存在的许可/通知文件汇总至 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)。其中原文合计 **188,951 字节**，不含新增的索引标题和分隔符；每份嵌入原文均与原文件逐字节比对一致。表中原相对路径可直接在汇总文本中搜索，原始来源为已检查测试环境的 `site-packages/` 下对应 `dist-info` 位置。以下 SHA-256 校验的是每份原文，不是新增标题或整个汇总文件：

| 汇总文本内的原相对路径标签 | 原文 SHA-256 |
|---|---|
| `dependency-notices/annotated_doc-0.0.5.dist-info/licenses/LICENSE` | `fff170779a6acbf65abdb405c087f1cee1786691e4a96a4034517e4a504a0cdf` |
| `dependency-notices/annotated_types-0.8.0.dist-info/licenses/LICENSE` | `fe1049884b1a0d9342901e88e07f32925d24b3121d9972b6a6805fb9824b095d` |
| `dependency-notices/anyio-4.15.1.dist-info/licenses/LICENSE` | `5361ac9dc58f2ef5fd2e9b09c68297c17f04950909bbc8023bdb82eacf22c2b0` |
| `dependency-notices/attrs-26.1.0.dist-info/licenses/LICENSE` | `882115c95dfc2af1eeb6714f8ec6d5cbcabf667caff8729f42420da63f714e9f` |
| `dependency-notices/certifi-2026.7.22.dist-info/licenses/LICENSE` | `e93716da6b9c0d5a4a1df60fe695b370f0695603d21f6f83f053e42cfc10caf7` |
| `dependency-notices/cffi-2.1.1.dist-info/licenses/LICENSE` | `5ba24ddc57067f9249add644c3afc41a5d6dc37e23433ef759d95df370b0af63` |
| `dependency-notices/click-8.5.0.dist-info/licenses/LICENSE.txt` | `9a8ad106a394e853bfe21f42f4e72d592819a22805d991b5f3275029292b658d` |
| `dependency-notices/colorama-0.4.6.dist-info/licenses/LICENSE.txt` | `cac35c02686e5d04a5a7140bfb3b36e73aed496656e891102e428886d7930318` |
| `dependency-notices/cryptography-50.0.1.dist-info/licenses/LICENSE` | `3e0c7c091a948b82533ba98fd7cbb40432d6f1a9acbf85f5922d2f99a93ae6bb` |
| `dependency-notices/cryptography-50.0.1.dist-info/licenses/LICENSE.APACHE` | `aac73b3148f6d1d7111dbca32099f68d26c644c6813ae1e4f05f6579aa2663fe` |
| `dependency-notices/cryptography-50.0.1.dist-info/licenses/LICENSE.BSD` | `602c4c7482de6479dd2e9793cda275e5e63d773dacd1eca689232ab7008fb4fb` |
| `dependency-notices/fastapi-0.141.1.dist-info/licenses/LICENSE` | `4ec89ffc81485b97fec584b2d4a961032eeffe834453894fd9c1274906cc744e` |
| `dependency-notices/h11-0.16.0.dist-info/licenses/LICENSE.txt` | `37db5bb85926db28a427a25867f10b1232003aea1be69ccb851138adb8e6f361` |
| `dependency-notices/httpcore-1.0.9.dist-info/licenses/LICENSE.md` | `fdcb59154c74cbaba16a11242f7740bea9f23d6feb5547917d8c5f94a80392a5` |
| `dependency-notices/httpcore2-2.12.0.dist-info/licenses/LICENSE.md` | `c4df125c807b0613501e943a5c92496dd11d2c16604ce396097a8dde396304d9` |
| `dependency-notices/httptools-0.8.0.dist-info/licenses/LICENSE` | `1c028b059d7a58e14ccda38cabced698c591fe614ffbe4f721430446e86c8d69` |
| `dependency-notices/httptools-0.8.0.dist-info/licenses/vendor/http-parser/LICENSE-MIT` | `5cd1b682c0ccbac0cb31b86a9a1104c3e2e7b1377a282b8169d2694b400db7c2` |
| `dependency-notices/httptools-0.8.0.dist-info/licenses/vendor/llhttp/LICENSE` | `279012e02a10acfd59a3f2d8f13a497332535d871c2b27c89988985b06a3a438` |
| `dependency-notices/httpx-0.28.1.dist-info/licenses/LICENSE.md` | `4ec59d544f12b5f539a3a716fd321ac58ccd8030b465221f2c880200cdf28d8d` |
| `dependency-notices/httpx2-2.12.0.dist-info/licenses/LICENSE.md` | `7e7d6dbaf7fe160d39fd6e84fd02c33cab96bcbea34d36998d545bceb4a19c30` |
| `dependency-notices/idna-3.19.dist-info/licenses/LICENSE.md` | `1a9a4f0e3d479a27240ddd59a9137a66ab4a0f9dfdc8ca6188cc0bfd85187f04` |
| `dependency-notices/jsonschema-4.26.0.dist-info/licenses/COPYING` | `4f92a015a13c4d1a040bef018aa13430b4f1bc73b41b16bb846c346766de7439` |
| `dependency-notices/jsonschema_specifications-2025.9.1.dist-info/licenses/COPYING` | `42dcd63495f87b4eb7c7757afa379bb55a53f94afd7a5f657d9adf57236e515c` |
| `dependency-notices/markdown_it_py-4.2.0.dist-info/licenses/LICENSE` | `4a2260d6e2cd0f5a151a1e86dbfe7d3ed552b1e2beabf9941c1ba5c49cbce484` |
| `dependency-notices/markdown_it_py-4.2.0.dist-info/licenses/LICENSE.markdown-it` | `792c48c5a849a15fdf9e37e8bcf9e6d1dd13b32b46c642a748a0a46a9919d473` |
| `dependency-notices/mcp-2.2.0.dist-info/licenses/LICENSE` | `5e13dbbc1d120fc2a03cecde7c91424ae2d7de11b63d58ded2f4431e261ee50d` |
| `dependency-notices/mcp_types-2.2.0.dist-info/licenses/LICENSE` | `5e13dbbc1d120fc2a03cecde7c91424ae2d7de11b63d58ded2f4431e261ee50d` |
| `dependency-notices/mdurl-0.1.2.dist-info/LICENSE` | `7c605df6e28667a9603118e98274f64a49ce3eed0d26fccce9534a345e0ef955` |
| `dependency-notices/opentelemetry_api-1.44.0.dist-info/licenses/LICENSE` | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |
| `dependency-notices/pycparser-3.0.dist-info/licenses/LICENSE` | `0c846399369ea76ddd7b5c44fe6d16497415fcf015f5cbb508c24bf98b81c5b1` |
| `dependency-notices/pydantic-2.13.5.dist-info/licenses/LICENSE` | `a9e186f3ca16b5eef84318e7a701721351a00cb7b8ae3a4394b67b49e3529ef3` |
| `dependency-notices/pydantic_core-2.46.5.dist-info/licenses/LICENSE` | `fbe7f615f18d135c07000e5a86325db27f42c7729699ef166ac1f7a3f4586bf4` |
| `dependency-notices/pygments-2.21.0.dist-info/licenses/AUTHORS` | `71a83872ad82f57be692cf827e048e2cd51d45169cfa1ea3f28706d97a872c0f` |
| `dependency-notices/pygments-2.21.0.dist-info/licenses/LICENSE` | `a9d66f1d526df02e29dce73436d34e56e8632f46c275bbdffc70569e882f9f17` |
| `dependency-notices/pyjwt-2.14.0.dist-info/licenses/AUTHORS.rst` | `925ce43461029eedbf558ec0b7cf7fc4b045def5120ebb97937c70814071cf07` |
| `dependency-notices/pyjwt-2.14.0.dist-info/licenses/LICENSE` | `797a7a20231d4c433e9f1911db1731d06b5828b98f499819a034f7c0f56f5ce5` |
| `dependency-notices/python_dotenv-1.2.3.dist-info/licenses/LICENSE` | `80619b7049f08c81683ad0e01f08f257a840652dd71ee83146d36658c7d2c2b9` |
| `dependency-notices/python_multipart-0.0.32.dist-info/licenses/LICENSE.txt` | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| `dependency-notices/pywin32-312.dist-info/licenses/adodbapi/license.txt` | `5ea2f23c7f00c3006bacf267183e816d8d4b6dc95ea57a4ddb0ff81de6d8719e` |
| `dependency-notices/pywin32-312.dist-info/licenses/com/License.txt` | `fad39c18fc3825fa278db1c86fd52cf88d7c525b3c2fbf7817fa383cbae4d423` |
| `dependency-notices/pywin32-312.dist-info/licenses/com/win32comext/mapi/src/MAPIStubLibrary/LICENSE` | `1c4cf44d2fb8bf2d10214d6da80cc9e05502824cc4460f35be4c7bcb4cde53da` |
| `dependency-notices/pywin32-312.dist-info/licenses/isapi/README.txt` | `41383bcc95edb8138d37077ae54bfdcbd2a3b77bf745a8529a9c161146e22303` |
| `dependency-notices/pywin32-312.dist-info/licenses/pythonwin/License.txt` | `a74d826efb242db087b850348e20abbfd591b51e2081f2048735290913872924` |
| `dependency-notices/pywin32-312.dist-info/licenses/pythonwin/pywin/idle/LICENSE.txt` | `a0fa1e7b8a4230055685e796548ac084a6c0eea395294574093bba72efd9191b` |
| `dependency-notices/pywin32-312.dist-info/licenses/pythonwin/Scintilla/License.txt` | `57ec79bbeab4fd1cf7460a7ad450d2ab01471810459aeae9e75e4c66b472095f` |
| `dependency-notices/pywin32-312.dist-info/licenses/win32/License.txt` | `a74d826efb242db087b850348e20abbfd591b51e2081f2048735290913872924` |
| `dependency-notices/pyyaml-6.0.3.dist-info/licenses/LICENSE` | `8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4` |
| `dependency-notices/referencing-0.37.0.dist-info/licenses/COPYING` | `42dcd63495f87b4eb7c7757afa379bb55a53f94afd7a5f657d9adf57236e515c` |
| `dependency-notices/rich-15.0.0.dist-info/licenses/LICENSE` | `deed7c17a4318158190a3ea239cc879a5a50271cebb98ae7025f48fbe58dca15` |
| `dependency-notices/rpds_py-2026.6.3.dist-info/licenses/LICENSE` | `8bcb72c82ea8ae74802293c41d93ad7d51434001b0ae45a603a5af0f507aee0a` |
| `dependency-notices/shellingham-1.5.4.dist-info/LICENSE` | `f388fd38cad13112c1dc0f669bbe80e7f84541edbafb72f3030d2ca7642c3c9d` |
| `dependency-notices/sse_starlette-3.4.11.dist-info/licenses/AUTHORS` | `c2ff63d2ecf128bbda8ab1b2016830a5da124202fbb97168685bb9946aed3f1a` |
| `dependency-notices/sse_starlette-3.4.11.dist-info/licenses/LICENSE` | `80af6bfccbebd2c14d4aab96695cab9950e177190cc80f5ef819e99996883e8e` |
| `dependency-notices/starlette-1.6.0.dist-info/licenses/LICENSE.md` | `dcb95677a02240243187e964f941847d19b17821cf99e5afae684fab328c19bf` |
| `dependency-notices/truststore-0.10.4.dist-info/licenses/LICENSE` | `33be7b7e8fa4fd19b1760e1a8ed8a668bdab852c91b692dd41424bcb725a9fca` |
| `dependency-notices/typer-0.27.2.dist-info/licenses/LICENSE` | `58992cebcf8dfb6e40c4e2112ed12126c243666dca3912a3d78b7ecac4859d49` |
| `dependency-notices/typing_extensions-4.16.0.dist-info/licenses/LICENSE` | `3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf` |
| `dependency-notices/typing_inspection-0.4.4.dist-info/licenses/LICENSE` | `804b59b25f2c31bd278f9202a19ae49a3945aa2664387e2d0a128c7cacc61ec3` |
| `dependency-notices/uvicorn-0.53.0.dist-info/licenses/LICENSE.md` | `efe1acf3e62fb99c288b0ec73e5a773b7268ef4320fe757ea994214e4b63c371` |
| `dependency-notices/watchfiles-1.2.0.dist-info/licenses/LICENSE` | `2d40a03346bded8daa4bd22d23825a6f2568a0820fbef76ac05bae534421e189` |
| `dependency-notices/websockets-17.1.dist-info/licenses/LICENSE` | `0f44514998aca209d3482d10204a8adf2aa4296ff157a36a5c0922f2280632d3` |
| `dependency-notices/iniconfig-2.3.0.dist-info/licenses/LICENSE` | `3409fa91f7ace557894632676656e32264fe5ef7581535725dc9a23774551bd4` |
| `dependency-notices/packaging-26.3.dist-info/licenses/LICENSE` | `cad1ef5bd340d73e074ba614d26f7deaca5c7940c3d8c34852e65c4909686c48` |
| `dependency-notices/packaging-26.3.dist-info/licenses/LICENSE.APACHE` | `0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594` |
| `dependency-notices/packaging-26.3.dist-info/licenses/LICENSE.BSD` | `b70e7e9b742f1cc6f948b34c16aa39ffece94196364bc88ff0d2180f0028fac5` |
| `dependency-notices/pluggy-1.6.0.dist-info/licenses/LICENSE` | `d6b65e6c213a5d0b577911d34d6e5949b9f59d76c238c5071a2f3fc16cfb2606` |
| `dependency-notices/pytest-9.1.1.dist-info/licenses/LICENSE` | `ca836a5f9ecca3b2f350230faa20a48fb8b145653b5568d784862df864706b9b` |
| `dependency-notices/pytest_asyncio-1.4.0.dist-info/licenses/LICENSE` | `a8ad31b1c3f40dca5a84119351b8fa8ddc868edd77fad8a8ebf6d8f2d16fa4ae` |
