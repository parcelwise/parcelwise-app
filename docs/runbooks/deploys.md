# Deploys and rollbacks

Merges to `main` deploy to staging, run the smoke test, then deploy to production. Nobody deploys by hand.

## Roll back

1. `fly releases -a parcelwise-api` and find the last good release.
2. `fly deploy -a parcelwise-api --image <image of that release>`.
3. Post in #incidents with the release you rolled back from.

Migrations only add columns, so rolling back code never needs a down migration.
