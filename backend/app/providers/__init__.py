"""Provider interfaces and implementations.

Every external dependency (broker, market data, ETF holdings) sits behind an
interface so the prototype runs on mock/seed data and can be upgraded without
touching business logic.
"""
