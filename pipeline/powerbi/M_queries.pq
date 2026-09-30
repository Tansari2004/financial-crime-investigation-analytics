// Power Query examples. Set Server and Database to your local PostgreSQL values.
// Create one query per expression in Power BI Desktop.

let
    Source = PostgreSQL.Database("localhost:5433", "banking_pipeline"),
    Daily = Source{[Schema="analytics", Item="v_daily_metrics"]}[Data]
in
    Daily

let
    Source = PostgreSQL.Database("localhost:5433", "banking_pipeline"),
    Alerts = Source{[Schema="analytics", Item="v_risk_alert"]}[Data]
in
    Alerts

let
    Source = PostgreSQL.Database("localhost:5433", "banking_pipeline"),
    Rows = Source{[Schema="analytics", Item="file_row_reconciliation"]}[Data]
in
    Rows

let
    Source = PostgreSQL.Database("localhost:5433", "banking_pipeline"),
    Amounts = Source{[Schema="analytics", Item="file_amount_reconciliation"]}[Data]
in
    Amounts

let
    Source = PostgreSQL.Database("localhost:5433", "banking_pipeline"),
    Health = Source{[Schema="analytics", Item="v_pipeline_health"]}[Data]
in
    Health

let
    Source = PostgreSQL.Database("localhost:5433", "banking_pipeline"),
    Evaluation = Source{[Schema="analytics", Item="v_risk_evaluation"]}[Data]
in
    Evaluation
