import { ref } from 'vue'

import { defineStore } from 'pinia'

import * as providersApi from '@/api/providers'
import type {
  ModelBinding,
  ModelBindingSavePayload,
  Provider,
  ProviderCreatePayload,
  ProviderUpdatePayload,
} from '@/api/types'

export const useModelStore = defineStore('model', () => {
  // ---------- 提供商 ----------
  const providers = ref<Provider[]>([])
  const providersLoading = ref(false)
  const providerSubmitting = ref(false)

  // ---------- 每阶段绑定 ----------
  const bindings = ref<ModelBinding[]>([])
  const bindingsLoading = ref(false)
  const bindingsSaving = ref(false)

  async function fetchProviders(): Promise<Provider[]> {
    providersLoading.value = true
    try {
      providers.value = await providersApi.listProviders()
      return providers.value
    } finally {
      providersLoading.value = false
    }
  }

  async function createProvider(payload: ProviderCreatePayload): Promise<Provider> {
    providerSubmitting.value = true
    try {
      const provider = await providersApi.createProvider(payload)
      await fetchProviders().catch(() => undefined)
      return provider
    } finally {
      providerSubmitting.value = false
    }
  }

  async function updateProvider(id: number, payload: ProviderUpdatePayload): Promise<Provider> {
    providerSubmitting.value = true
    try {
      const provider = await providersApi.updateProvider(id, payload)
      await fetchProviders().catch(() => undefined)
      return provider
    } finally {
      providerSubmitting.value = false
    }
  }

  async function removeProvider(id: number): Promise<void> {
    await providersApi.deleteProvider(id)
    await fetchProviders()
  }

  async function fetchBindings(projectId: number): Promise<ModelBinding[]> {
    bindingsLoading.value = true
    try {
      bindings.value = await providersApi.listModelBindings(projectId)
      return bindings.value
    } finally {
      bindingsLoading.value = false
    }
  }

  async function saveBindings(payload: ModelBindingSavePayload): Promise<ModelBinding[]> {
    bindingsSaving.value = true
    try {
      bindings.value = await providersApi.saveModelBindings(payload)
      return bindings.value
    } finally {
      bindingsSaving.value = false
    }
  }

  function reset(): void {
    providers.value = []
    bindings.value = []
  }

  return {
    providers,
    providersLoading,
    providerSubmitting,
    bindings,
    bindingsLoading,
    bindingsSaving,
    fetchProviders,
    createProvider,
    updateProvider,
    removeProvider,
    fetchBindings,
    saveBindings,
    reset,
  }
})
