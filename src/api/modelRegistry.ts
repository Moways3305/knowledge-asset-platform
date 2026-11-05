import { apiGet, apiPost, apiPut } from "./http";
import type {
  ConnectionInput,
  ProviderConnection,
  ProviderTemplate,
  RegistryInventory,
  RegistryModel,
  RegistryModelInput,
} from "../types/modelRegistry";
const BASE = "/api/v1/admin/model-registry";
export const fetchRegistry = () => apiGet<RegistryInventory>(BASE);
export const fetchProviderCatalog = () =>
  apiGet<{ providers: ProviderTemplate[] }>(`${BASE}/catalog`);
export const createProviderConnection = (body: ConnectionInput) =>
  apiPost<ProviderConnection>(`${BASE}/connections`, body);
export const updateProviderConnection = (id: string, body: ConnectionInput) =>
  apiPut<ProviderConnection>(`${BASE}/connections/${id}`, body);
export const createRegisteredModel = (body: RegistryModelInput) =>
  apiPost<RegistryModel>(`${BASE}/models`, body);
export const updateRegisteredModel = (id: string, body: RegistryModelInput) =>
  apiPut<RegistryModel>(`${BASE}/models/${id}`, body);
export const verifyRegisteredModel = (model: RegistryModel) =>
  apiPost<RegistryModel>(`${BASE}/models/${model.id}/verify`, { signature: model.signature });
export const syncRegisteredModel = (model: RegistryModel) =>
  apiPost<RegistryModel>(`${BASE}/models/${model.id}/sync`, { signature: model.signature });
