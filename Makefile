.PHONY: setup run api test check

setup:
	python -m pip install -r requirements-dev.txt

run:
	streamlit run app.py

api:
	python run_api.py

test:
	python -m pytest -q

check: test
	python -m compileall -q . -x 'quantpilot.db|docs'
