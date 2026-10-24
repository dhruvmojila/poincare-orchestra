# Security policy

`poincare-orchestra` makes network calls only through the provider you configure (the bundled mock providers make none), reads the scenario files you pass to it, and stores nothing outside the paths you choose. Treat scenario files and provider credentials as you would any configuration: do not load scenario files from untrusted sources, and pass provider keys through the environment variables your provider documents, never inside scenarios.

If you find a vulnerability, email dhruvmojila098@gmail.com with details. You will get an acknowledgement within a week and a fix or mitigation plan as soon as the issue is confirmed. Please do not open a public issue for security reports.
