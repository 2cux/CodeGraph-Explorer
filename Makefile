install:
	pip install -e "backend[mcp,watch]"

update:
	git pull
	pip install -e "backend[mcp,watch]"

uninstall:
	pip uninstall -y codegraph-explorer

configure:
	codegraph configure all

init-demo:
	cd examples/demo_python_project && codegraph init

status:
	codegraph status

dashboard:
	cd frontend && npm install && npm run dev

benchmark:
	python -m tests.agent_benchmark.runner --mode baseline
	python -m tests.agent_benchmark.runner --mode codegraph
	python -m tests.agent_benchmark.report

demo: install configure init-demo status
	codegraph context "add MFA to login flow"
