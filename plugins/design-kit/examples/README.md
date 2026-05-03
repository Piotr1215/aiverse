# Design-Kit Examples

This directory contains real-world examples of Design-Kit workflows.

## Available Examples

### [API with Authentication](api-with-auth/)
A REST API with OAuth2 authentication and rate limiting.

**Demonstrates**:
- Breaking down a complex API into parallel proofs
- Contract-based integration between auth and API layers
- Test harness setup for HTTP endpoints
- Iterative refinement based on feedback

**Key Learnings**:
- How to structure authentication as an independent proof
- Testing strategies for rate limiting
- Integration patterns for API middleware

## Contributing Your Example

Have a great Design-Kit workflow to share? We'd love to include it!

### What Makes a Good Example?

- **Real-world problem**: Not a toy example, but actual production-like complexity
- **Complete workflow**: Shows all three phases (Plan, Research, Integrate)
- **Clear learnings**: Documents what worked, what didn't, and why
- **Anonymized**: No sensitive data or proprietary information

### How to Contribute

1. Create a new directory under `examples/` with a descriptive name
2. Include these files:
   - `README.md` - Overview and context
   - `PLAN.md` - Your master plan (anonymized if needed)
   - Sample `CONTRACT.md` from one of your proofs
   - Sample `TESTING.md` showing your test strategy
   - `LEARNINGS.md` - Key insights and discoveries

3. Submit a pull request with your example

### Template Structure

```
examples/your-project/
├── README.md           # Project overview
├── PLAN.md             # Master plan
├── proofs/
│   └── component-name/
│       ├── CONTRACT.md
│       └── TESTING.md
└── LEARNINGS.md        # Key insights
```

## Example Ideas

We're particularly interested in examples for:

- **Microservices**: Multi-service architectures
- **Data Pipelines**: ETL and data processing
- **DevOps Tools**: CI/CD, deployment automation
- **ML Workflows**: Model training and deployment
- **Cloud Infrastructure**: Kubernetes, Terraform, etc.
- **Full-stack Apps**: Frontend + Backend integration

## Need Help?

If you have a workflow to share but need help structuring it as an example:
1. Open an issue with the `workflow-example` template
2. Describe your project and what you learned
3. We'll help you format it for inclusion

---

Examples are the best way to learn Design-Kit. Share your success stories!
