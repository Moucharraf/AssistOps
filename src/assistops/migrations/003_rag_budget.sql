-- Reserve before external calls; never refund uncertain or failed requests.
CREATE TABLE rag_daily_budget (
    day date PRIMARY KEY,
    attempts integer NOT NULL CHECK (attempts > 0)
);
