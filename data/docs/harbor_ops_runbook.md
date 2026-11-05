# Harbor Operations Runbook

## Purpose

This runbook describes how the platform team operates services deployed with Harbor. It covers incident handling, on-call duties, backups, and autoscaling. It is written for engineers who are on call for the first time, so it explains the reasoning behind each rule as well as the rule itself.

## Incident severity

Every incident is given a severity level when it is opened. A SEV1 incident means customers cannot use the service at all, or data is at risk. A SEV2 incident means a major feature is broken or the service is badly degraded, but a workaround exists. A SEV3 incident is a minor problem that does not stop customers from working.

The acknowledgement targets differ by level. A SEV1 incident must be acknowledged within 5 minutes of the first page. A SEV2 incident must be acknowledged within 30 minutes. A SEV3 incident is picked up by the end of the next business day. Acknowledging an incident means a named engineer has taken ownership, not that the problem is fixed.

When two people disagree about severity, choose the higher level and lower it later. It is cheaper to downgrade an incident than to explain a slow response.

## On-call rotation

The on-call rotation is weekly. The handoff happens on Mondays at 10:00 UTC, and the outgoing engineer writes a short summary of open issues in the team channel before the handoff. The incoming engineer replies to confirm that they have read it.

Each rotation has a primary and a secondary engineer. The secondary is paged only if the primary does not acknowledge an alert within 10 minutes. Engineers who are unavailable during their week must swap with a teammate at least 2 days ahead, and the swap is recorded in the rotation calendar.

## Postmortems

Every SEV1 and SEV2 incident needs a written postmortem. The postmortem is due within 5 business days of the incident being closed. It describes the timeline, the root cause, what went well, and the follow-up actions with owners. Postmortems are blameless: they describe how the system allowed the failure, not who made a mistake.

## Autoscaling

Services scale automatically between a minimum of 2 instances and a maximum of 20 instances. Two instances are the minimum so that one instance can be replaced without downtime. Harbor adds an instance when average CPU stays above 70% for 5 minutes. It removes an instance when average CPU stays below 30% for 15 minutes. After any scaling action there is a cooldown of 10 minutes before the next action can happen, which prevents the instance count from oscillating.

If a service regularly reaches the maximum of 20 instances, do not simply raise the limit. First check whether a slow query or a memory leak is driving the load.

## Backups

The platform database is backed up nightly at 02:30 UTC. Backups are kept for 35 days and then deleted automatically. Once a month, the on-call engineer restores the most recent backup into a scratch environment and runs the smoke tests against it. A backup that has never been restored is not considered a working backup.

Backups are encrypted at rest and stored in a different region from the primary database.

## Access control

Production access is granted per person and reviewed every quarter. Engineers use short-lived credentials that are issued through the dashboard, and shared accounts are not allowed. Any use of production credentials is written to an audit log. Requests for elevated access must name a ticket and are approved by a second engineer.

## Alert hygiene

An alert should be actionable. If an alert fires and the on-call engineer does nothing, the alert is a candidate for deletion or for a higher threshold. The team reviews the noisiest alerts at the start of each month and removes or tunes the ones that did not lead to any action.
