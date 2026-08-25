.PHONY: test deploy status report images

test:
	python3 -m pytest -q

deploy:
	./deploy.sh

status:
	systemctl --user status alpha3-dry-runner.service alpha3-tg-bot.service

report:
	python3 scripts/generate_hedge_report.py

images:
	python3 scripts/draw_pipeline.py
	python3 scripts/draw_topology.py

help:
	@echo "make test      - run 27-test suite (green gate)"
	@echo "make deploy    - run deploy.sh (systemd setup)"
	@echo "make status    - show service status"
	@echo "make report    - regenerate docs/HEDGE_REPORT.md"
	@echo "make images    - regenerate docs/images/*.png"
