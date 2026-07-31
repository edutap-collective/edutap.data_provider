# edutap.data_provider

`edutap.data_provider` answers one question for a consumer inside a university:
*which fields may this pass-issuing service see for this one person?* It declares a
catalogue per view type, projects a stored row onto exactly the fields a caller asks
for, and computes derived fields — such as a pass validity — at read time from a
closed rule language. It is read-only without exception: it creates no table, writes
no row, and judges no pass lifecycle transition. Producers outside the service fill
the two tables it reads, and `edutap.db_definitions` applies their schema with a
privileged database user.

```{toctree}
:maxdepth: 2

tutorial
how-to
reference
explanation
```
