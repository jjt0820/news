# backend

MSA backend services: user-service, mail-service, news-fetcher-service, news-summarizer-service.

## Docker builds

Build context is this backend/ directory. Dockerfiles live here (matches infra Jenkins paths).

    docker build -f backend/Dockerfile.user backend
    docker build -f backend/Dockerfile.mail backend
    docker build -f backend/Dockerfile.fetcher backend
    docker build -f backend/Dockerfile.summarizer backend

From inside backend/:

    docker build -f Dockerfile.user .
