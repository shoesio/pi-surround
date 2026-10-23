check:
	python3 -m unittest discover -s tests -v
	python3 scripts/audit_release.py

native:
	$(MAKE) -C native

.PHONY: check native
