IMAGE_NAME ?= mongodb-compass
IMAGE_TAG ?= local
PLATFORM ?= linux/amd64
K8S_EXAMPLE ?= secrets/compass.yaml
export IMAGE_NAME IMAGE_TAG PLATFORM

.PHONY: build up down logs test smoke-test scan push ecr-create
build:
	./scripts/build.sh
up:
	docker compose up -d
down:
	docker compose down
logs:
	docker compose logs -f compass
test:
	python3 -m unittest discover -s tests -v
	shellcheck scripts/*.sh
smoke-test:
	python3 tests/smoke_ui.py
scan:
	./scripts/scan-image.sh
push:
	./scripts/ecr.sh push
ecr-create:
	./scripts/ecr.sh create

.PHONY: eks-render eks-validate eks-deploy eks-status eks-port-forward eks-restart
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
eks-port-forward:
	kubectl -n mongodb-compass port-forward --address=127.0.0.1 service/mongodb-compass 6080:6080
eks-restart:
	kubectl -n mongodb-compass rollout restart deployment/mongodb-compass
	kubectl -n mongodb-compass rollout status deployment/mongodb-compass --timeout=300s
