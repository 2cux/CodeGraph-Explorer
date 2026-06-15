install:
	pip install -e "backend[mcp,watch]"

update:
	git pull
	pip install -e "backend[mcp,watch]"

uninstall:
	pip uninstall -y codegraph-explorer

init:
	codegraph init .

configure:
	codegraph configure all

doctor:
	codegraph doctor

serve:
	codegraph serve --mcp

watch:
	codegraph watch .

status:
	codegraph status

benchmark:
	python -m tests.agent_benchmark.runner --mode baseline
	python -m tests.agent_benchmark.runner --mode codegraph --response-mode compact
	python -m tests.agent_benchmark.runner --mode codegraph --response-mode standard
	python -m tests.agent_benchmark.report

benchmark-gate:
	python -m tests.agent_benchmark.gate

adoption-template:
	python -m tests.agent_benchmark.adoption --write-template

adoption-report:
	python -m tests.agent_benchmark.adoption

test:
	pytest backend/tests/

mcp-check:
	codegraph serve --mcp --check

demo: install configure init status
	codegraph context "add MFA to login flow"
