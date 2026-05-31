install:
	pip install -e "backend[mcp,watch]"

configure:
	codegraph configure all

init-demo:
	codegraph init ./examples/demo_python_project

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
