.PHONY: test demo preview app compare
test:
	python -m unittest discover -s tests -v
demo:
	python -m praxis run --provider demo --setup baseline
preview:
	python scripts/dev_server.py
app:
	uvicorn app:app --reload
compare:
	python -m praxis compare --provider $(or $(PROVIDER),gemini) --runs 5
