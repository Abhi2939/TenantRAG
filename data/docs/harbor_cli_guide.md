# Harbor CLI Guide

## Overview

Harbor is a command-line tool for deploying web services to managed container hosts. It packages your application, uploads it, starts new instances, checks that they are healthy, and then shifts traffic to them. Harbor was built for small teams that want repeatable releases without running their own orchestration layer. Version 2.0 introduced the harbor.toml configuration file and the canary release mode described later in this guide.

## Installation

Harbor ships as a single binary. It runs on 64-bit Linux and on macOS 13 or newer. After downloading the binary, place it somewhere on your PATH and run harbor version to confirm that it starts. Harbor does not need Docker to be installed on your machine, because image building happens on the remote build service.

To sign in, run harbor login. The command opens a browser window and stores an API token in your home directory. API tokens expire after 30 days, and you must run harbor login again once a token has expired. For automated pipelines, create a service token from the dashboard instead of using a personal login. The Harbor API allows 120 requests per minute per token, and requests above that limit receive an HTTP 429 response.

## Configuration

Every project has a harbor.toml file in its root directory. The file lists the service name, the build command, the port the service listens on, and the health check settings. Harbor reads configuration from four places. The order of precedence is command-line flags, then environment variables, then harbor.toml, then built-in defaults. A value set higher in that list always overrides a value set lower down.

The default region is eu-north, and a project can be moved to another region only by redeploying it. You can set a different region in harbor.toml or pass the region flag to a single deploy command. Regions cannot be mixed within one release, so every instance of a release runs in the same place.

Environment variables for your application are defined in the env section of harbor.toml. Values that should not be committed to version control belong in secrets, which are covered below.

## Deploying

The basic command is harbor deploy. Harbor builds your service on the remote build service, uploads the image, and starts new instances beside the old ones. Once the new instances pass their health checks, traffic moves across and the old instances are stopped.

Use harbor deploy --dry-run to see what a deploy would do without changing anything. A dry run prints the build plan, the target region, and the number of instances, then exits. It is a good habit to run a dry run before the first deploy of a new project.

A single deploy waits up to 90 seconds for new instances to become healthy. If the instances are not healthy by then, the deploy is marked as failed and the old instances keep serving traffic. You can raise this limit with the deploy_timeout setting in harbor.toml. Each project can run at most 3 concurrent deploys, and additional deploys are queued until one of the running deploys finishes.

## Health checks

Harbor probes every new instance before it receives traffic. The default health check path is /healthz, and the service should return an HTTP 200 response when it is ready. Harbor sends a probe every 15 seconds. An instance is marked unhealthy after 4 consecutive failed checks, and an unhealthy instance is replaced automatically. You can change the path and the interval in the health section of harbor.toml.

A common mistake is to make the health endpoint depend on a slow external service. If the database is briefly unavailable, every instance fails its probe at once and Harbor replaces all of them. Keep the health endpoint cheap and local.

## Canary releases

Canary mode sends a small share of real traffic to the new release before everyone gets it. Enable it with harbor deploy --canary. By default the canary receives 10% of traffic for 12 minutes. If the error rate stays within the configured limit during that window, Harbor promotes the release to 100% of traffic. If the error rate goes above the limit, Harbor rolls the canary back automatically and keeps the previous release serving all traffic.

You can change the traffic share and the duration with the canary_percent and canary_minutes settings in harbor.toml.

## Rollbacks

Every successful deploy creates a numbered release. Harbor keeps the last 7 releases for each project, and older releases are removed to save storage. To go back to an earlier release, run harbor rollback followed by the release number. A rollback does not rebuild anything, so it normally finishes in a few seconds. If you run harbor rollback without a number, Harbor returns to the release that was live immediately before the current one.

## Secrets

Secrets are values such as database passwords and API keys. Add one with harbor secrets set NAME. Secrets are encrypted with AES-256-GCM before they leave your machine, and Harbor injects them into your service as environment variables at start time. A single secret value must be no larger than 48 KB. Changing a secret does not restart running instances by itself, so run a new deploy to pick up the change.

## Logs

Run harbor logs to print recent log lines for a service. Add the follow flag to stream new lines as they arrive. Logs are kept for 14 days on the standard plan and for 60 days on the premium plan. After the retention period ends, log lines are deleted and cannot be recovered. If you need logs for longer, forward them to an external log store using a log drain.
