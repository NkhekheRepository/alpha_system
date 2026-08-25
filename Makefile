.PHONY: test deploy status report images

test:
	python3 -m pytest -q

deploy:
	./deploy.sh

status:
	systemctl --user status alpha3-dry-runner.service alpha3-tg-bot.service

kill:
	python3 alpha3_dry_runner.py --kill

disarm:
	python3 alpha3_dry_runner.py --disarm

report:
	python3 scripts/generate_hedge_report.py

images:
	python3 scripts/draw_pipeline.py
	python3 scripts/draw_topology.py

help:
	@echo "make test      - run 27-test suite (green gate)"
	@echo "make deploy    - run deploy.sh (systemd setup)"
	@echo "make status    - show service status"
	@echo "make kill      - arm kill switch (flatten all once, then COOL)"
	@echo "make disarm    - disarm kill switch, re-enable trading"
	@echo "make report    - regenerate docs/HEDGE_REPORT.md"
	@echo "make images    - regenerate docs/images/*.png"
