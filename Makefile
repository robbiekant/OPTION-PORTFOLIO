.PHONY: install run offline build report dashboard clean test

install:
	pip install -r requirements.txt --break-system-packages -q

run:            ## live pull (needs IB Gateway) + build + both HTML outputs
	python -m thetaforge.cli run

offline:        ## rebuild from the committed snapshot, no network
	python -m thetaforge.cli run --offline

build:          ## construct the book and print the audit
	python -m thetaforge.cli build

report:
	python -m thetaforge.cli report

dashboard:
	python -m thetaforge.cli dashboard

test:           ## smoke test across stances and portfolio sizes
	python -m thetaforge.cli build >/dev/null
	python -m thetaforge.cli --stance conservative build >/dev/null
	python -m thetaforge.cli --stance aggressive build >/dev/null
	python -m thetaforge.cli --nlv 1000000 build >/dev/null
	@echo "smoke tests passed"

clean:
	rm -rf output/*.html
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
