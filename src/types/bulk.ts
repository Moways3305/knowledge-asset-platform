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

export interface IngestBulkItemResultDTO extends BulkItemResultDTO {
  result_asset_id?: string;
  index_status?: string | null;
}

export interface IngestBulkOperationResponseDTO extends Omit<BulkOperationResponseDTO, "items"> {
  items: IngestBulkItemResultDTO[];
}
