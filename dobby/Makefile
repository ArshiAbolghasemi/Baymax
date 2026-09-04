# Development entry points for dobby.

BINARY  := dobby
BIN_DIR := bin
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)

.PHONY: all
all: fmt vet lint test build

.PHONY: build
build: ## Compile the server into bin/
	@mkdir -p $(BIN_DIR)
	go build -trimpath -o $(BIN_DIR)/$(BINARY) ./cmd/$(BINARY)

.PHONY: run
run: ## Run the server
	go run ./cmd/$(BINARY)

.PHONY: fmt
fmt: ## Rewrite source files with the configured formatters
	golangci-lint fmt

.PHONY: vet
vet: ## Run go vet
	go vet ./...

.PHONY: lint
lint: ## Run golangci-lint
	golangci-lint run ./...

.PHONY: lint-fix
lint-fix: ## Run golangci-lint with autofixes applied
	golangci-lint run --fix ./...

.PHONY: test
test: ## Run the test suite with the race detector
	go test -race -count=1 ./...

.PHONY: cover
cover: ## Run tests and print a coverage report
	go test -race -coverprofile=coverage.out ./...
	go tool cover -func=coverage.out

.PHONY: tidy
tidy: ## Prune and verify go.mod / go.sum
	go mod tidy
	go mod verify

.PHONY: clean
clean: ## Remove build output
	rm -rf $(BIN_DIR) coverage.out access.log

.PHONY: help
help: ## List available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
