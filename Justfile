python_version := "3.11"
interpreter    := ".env/bin/python" + python_version

test *args:
	{{interpreter}} -m pytest -vv {{args}}
