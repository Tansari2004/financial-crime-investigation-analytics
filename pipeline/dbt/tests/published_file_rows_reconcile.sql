SELECT m.file_id
FROM ops.file_manifest m
LEFT JOIN {{ source('analytics', 'file_row_reconciliation') }} r
  ON r.file_id = m.file_id
WHERE m.status = 'completed'
  AND (r.file_id IS NULL OR NOT r.is_balanced)
