# Software Bill of Materials (SBOM) for Perseus

This SBOM document lists all direct and transitive dependencies of the Perseus project, as required for federal procurement compliance.

## NTIA Minimum Elements Checklist

| Element                  | Status      | Notes                                                                                                                                                                                                                                                                          |
| :----------------------- | :---------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Data Fields**          |             |                                                                                                                                                                                                                                                                                |
| - Supplier Name          | Provided    | Perseus-Computing-LLC                                                                                                                                                                                                                                                          |
| - Component Name         | Provided    | Each Python package listed below.                                                                                                                                                                                                                                              |
| - Component Version      | Provided    | Version numbers are specified for each package.                                                                                                                                                                                                                                |
| - SPDX ID (or equivalent)| Not Provided| Not directly applicable for Python packages in requirements.txt. Package names serve as identifiers.                                                                                                                                                                          |
| - Hash of Component      | Not Provided| While `pip` can generate hashes, they are not included in this SBOM by default. Can be generated on request.                                                                                                                                                                  |
| - Relationship           | Provided    | All listed components are direct dependencies of Perseus.                                                                                                                                                                                                                      |
| - Author Timestamp       | Provided    | This document's creation date.                                                                                                                                                                                                                                                 |
| **Automation Support**   |             |                                                                                                                                                                                                                                                                                |
| - Format                 | Human-readable| Markdown format. Can be converted to machine-readable formats (e.g., SPDX, CycloneDX) if needed.                                                                                                                                                                               |
| **Practices and Processes** |         |                                                                                                                                                                                                                                                                                |
| - Frequency              | On Request  | Generated as part of the compliance process. Updated as dependencies change.                                                                                                                                                                                                   |
| - Depth                  | Transitive  | `pip freeze` captures all installed packages, which includes transitive dependencies.                                                                                                                                                                                          |
| - Distribution           | Included    | This document is included in the repository.                                                                                                                                                                                                                                   |
| - Access                 | Public      | This document is publicly available in the Perseus repository.                                                                                                                                                                                                                 |

## Python Dependencies

The following Python packages are used in the Perseus project. This list is generated using `pip freeze` from the project's virtual environment, capturing both direct and transitive dependencies.

**Note:** License information for each package is not automatically extracted by `pip freeze`. This would require additional tools (e.g., `pip-licenses` or `license-scanner`). For compliance, refer to the individual package repositories or distribution metadata for exact license terms.

```
annotated-doc==0.0.4
annotated-types==0.7.0
anthropic==0.111.0
anyio==4.14.0
ast_serialize==0.5.0
backports.zstd==1.6.0
blockbuster==1.5.26
build==1.5.0
CacheControl==0.14.4
certifi==2026.6.17
cffi==2.0.0
charset-normalizer==3.4.7
cleo==2.1.0
click==8.4.1
cloudpickle==3.1.2
coverage==7.14.2
crashtest==0.4.1
croniter==6.2.2
cryptography==49.0.0
distlib==0.4.3
distro==1.9.0
docstring_parser==0.18.0
docutils==0.23
dulwich==1.2.6
fastjsonschema==2.21.2
filelock==3.29.4
findpython==0.8.0
forbiddenfruit==0.1.4
googleapis-common-protos==1.75.0
grpcio==1.80.0
grpcio-health-checking==1.80.0
grpcio-tools==1.80.0
h11==0.16.0
hermes-agent==0.17.0
httpcore==1.0.9
httptools==0.8.0
httpx==0.28.1
id==1.6.1
idna==3.18
iniconfig==2.3.0
installer==1.0.1
jaraco.classes==3.4.0
jaraco.context==6.1.2
jaraco.functools==4.5.0
jeepney==0.9.0
jiter==0.15.0
jsonpatch==1.33
jsonpointer==3.1.1
jsonschema_rs==0.44.1
keyring==25.7.0
langchain-anthropic==1.4.6
langchain-core==1.4.8
langchain-openai==1.3.2
langchain-protocol==0.0.18
langgraph==1.2.6
langgraph-api==0.10.0
langgraph-checkpoint==4.1.1
langgraph-cli==0.4.30
langgraph-prebuilt==1.1.0
langgraph-runtime-inmem==0.30.0
langgraph-sdk==0.4.2
langsmith==0.8.18
librt==0.11.0
markdown-it-py==4.2.0
mdurl==0.1.2
more-itertools==11.1.0
msgpack==1.2.1
mypy==2.1.0
mypy_extensions==1.1.0
nh3==0.3.5
openai==2.43.0
opentelemetry-api==1.42.1
opentelemetry-exporter-otlp-proto-common==1.42.1
opentelemetry-exporter-otlp-proto-http==1.42.1
opentelemetry-proto==1.42.1
opentelemetry-sdk==1.42.1
opentelemetry-semantic-conventions==0.63b1
orjson==3.11.9
ormsgpack==1.12.2
packaging==26.2
pathspec==1.1.1
pbs-installer==2026.6.10
pdfminer.six==20260107
pdfplumber==0.11.10
pillow==12.2.0
pkginfo==1.12.1.2
platformdirs==4.10.0
pluggy==1.6.0
poetry==2.4.1
poetry-core==2.4.0
protobuf==6.33.6
pycparser==3.0
pydantic==2.13.4
pydantic_core==2.46.4
Pygments==2.20.0
PyJWT==2.13.0
pypdfium2==5.10.1
pyproject_hooks==1.2.0
pytest==9.1.1
pytest-asyncio==1.4.0
pytest-cov==7.1.0
python-dateutil==2.9.0.post0
python-discovery==1.4.2
python-dotenv==1.2.2
PyYAML==6.0.3
RapidFuzz==3.14.5
readme_renderer==45.0
regex==2026.5.9
requests==2.34.2
requests-toolbelt==1.0.0
rfc3986==2.0.0
rich==15.0.0
ruff==0.15.18
SecretStorage==3.5.0
setuptools==82.0.1
shellingham==1.5.4
six==1.17.0
sniffio==1.3.1
sse-starlette==3.3.4
starlette==1.3.1
structlog==25.5.0
tenacity==9.1.4
tiktoken==0.13.0
tomlkit==0.15.0
tqdm==4.68.3
trove-classifiers==2026.6.1.19
truststore==0.10.4
twine==6.2.0
typer==0.23.2
typing-inspection==0.4.2
typing_extensions==4.15.0
urllib3==2.7.0
uuid_utils==0.16.2
uvicorn==0.49.0
uvloop==0.22.1
virtualenv==21.5.1
watchfiles==1.2.0
websockets==15.0.1
xxhash==3.7.0
yara-python==4.5.4
zstandard==0.25.0
```
