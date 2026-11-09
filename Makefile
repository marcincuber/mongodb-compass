IMAGE_NAME ?= mongodb-compass
IMAGE_TAG ?= local
PLATFORM ?= linux/amd64
K8S_EXAMPLE ?= secrets/compass.yaml
export IMAGE_NAME IMAGE_TAG PLATFORM

.PHONY: build verify up down logs test smoke-test scan push ecr-create
build:
	./scripts/build.sh
verify:
	$(MAKE) test eks-validate
	$(MAKE) build
	$(MAKE) smoke-test
	$(MAKE) scan
up:
	docker compose up -d
down:
	docker compose down
logs:
	docker compose logs -f compass
test:
	python3 -m unittest discover -s tests -v
	node --test tests/test_mongo_proxy.cjs
	shellcheck scripts/*.sh test-script.sh
smoke-test:
	python3 tests/smoke_ui.py
scan:
	./scripts/scan-image.sh
push:
	./scripts/ecr.sh push
ecr-create:
	./scripts/ecr.sh create

.PHONY: eks-render eks-validate eks-deploy eks-status eks-port-forward eks-restart eks-check
eks-render:
	@cat "$(K8S_EXAMPLE)"
eks-validate:
	./scripts/validate-k8s.sh
eks-deploy:
	kubectl apply -f "$(K8S_EXAMPLE)"
	kubectl -n mongodb-compass rollout restart deployment/mongodb-compass
	kubectl -n mongodb-compass rollout status deployment/mongodb-compass --timeout=300s
eks-status:
	kubectl -n mongodb-compass get deployment,pods,service
eks-check:
	kubectl -n mongodb-compass exec deployment/mongodb-compass -c compass -- python3 /opt/compass-container/check_connection.py
eks-port-forward:
	kubectl -n mongodb-compass port-forward --address=127.0.0.1 service/mongodb-compass 6080:6080
eks-restart:
	kubectl -n mongodb-compass rollout restart deployment/mongodb-compass
	kubectl -n mongodb-compass rollout status deployment/mongodb-compass --timeout=300s
