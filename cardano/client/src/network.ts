import { RegistryError } from '#types';
import type { CardanoNetwork } from '#types';

export const DEGA_POLICY = '25c5de5f5b286073c593edfd77b48abc7a48e5a4f3d4cd9d428ff935';
export const DEGA_NAME = '44454741';
export function parseNetwork(value: unknown): CardanoNetwork {
  if (value !== 'Mainnet' && value !== 'Preview') {
    throw new RegistryError('INVALID_NETWORK', 'Explicit Mainnet or Preview network is required');
  }
  return value;
}
export function providerUrl(network: CardanoNetwork): string {
  return network === 'Mainnet'
    ? 'https://api.koios.rest/api/v1'
    : 'https://preview.koios.rest/api/v1';
}
export function validateProvider(network: CardanoNetwork, endpoint: string): void {
  if (endpoint !== providerUrl(network)) {
    throw new RegistryError(
      'INVALID_PROVIDER',
      'Provider endpoint does not match selected network',
    );
  }
}
export function validateFeeAsset(network: CardanoNetwork, policy: string, name: string): void {
  if (network === 'Mainnet' && (policy !== DEGA_POLICY || name !== DEGA_NAME)) {
    throw new RegistryError('INVALID_FEE_ASSET', 'Mainnet requires the verified DEGA native asset');
  }
  if (network === 'Preview' && policy === DEGA_POLICY) {
    throw new RegistryError('INVALID_FEE_ASSET', 'Preview requires a distinct mock asset policy');
  }
}
