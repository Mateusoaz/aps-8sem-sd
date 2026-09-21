-- Executado somente na primeira criação do volume.
-- As APIs criam seus próprios schemas e tabelas de forma idempotente.
SELECT 'aps_monitoramento inicializado' AS status;
