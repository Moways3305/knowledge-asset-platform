export interface BulkItemResultDTO {
  item_id: string;
  status: "succeeded" | "skipped" | "failed";
  reason_code: string | null;
  message: string | null;
}

export interface BulkOperationResponseDTO {
  operation_id: string;
  status: "completed" | "completed_with_errors";
  execution_mode: "synchronous" | "controlled_batch";
  submitted: number;
  succeeded: number;
  skipped: number;
  failed: number;
  items: BulkItemResultDTO[];
}
