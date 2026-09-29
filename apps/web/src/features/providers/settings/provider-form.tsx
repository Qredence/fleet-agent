import { Cpu, MessageSquare, Check } from 'lucide-react'
import type { FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { MessagesFormat, ResponseFormat } from '@/features/providers/providers-store'

export interface ProviderFormData {
  name: string
  apiKey: string
  modelId: string
  baseUrl: string
  responseFormat: ResponseFormat
  messagesFormat: MessagesFormat
}

interface SegmentedOption<T extends string> {
  value: T
  label: string
}

function SegmentedOptions<T extends string>({
  ariaLabel,
  value,
  options,
  onChange,
}: {
  ariaLabel: string
  value: T
  options: SegmentedOption<T>[]
  onChange: (value: T) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <Button
          key={option.value}
          variant={value === option.value ? 'default' : 'outline'}
          size="sm"
          onClick={() => onChange(option.value)}
          className="h-7 text-xs gap-1.5"
        >
          {value === option.value && <Check className="size-3" />}
          {option.label}
        </Button>
      ))}
    </div>
  )
}

const RESPONSE_FORMAT_OPTIONS: SegmentedOption<ResponseFormat>[] = [
  { value: 'native_function_calling', label: 'Native function calling' },
  { value: 'json_tool_calls', label: 'JSON tool calls' },
]

const MESSAGES_FORMAT_OPTIONS: SegmentedOption<MessagesFormat>[] = [
  { value: 'system_role', label: 'System role' },
  { value: 'developer_role', label: 'Developer role' },
]

interface ProviderFormProps {
  formData: ProviderFormData
  error: string | null
  onChange: (updater: (prev: ProviderFormData) => ProviderFormData) => void
  onSubmit: (e: FormEvent) => void
  onCancel: () => void
}

export function ProviderForm({
  formData,
  error,
  onChange,
  onSubmit,
  onCancel,
}: ProviderFormProps) {
  return (
    <form onSubmit={onSubmit} className="space-y-3 border-t pt-3">
      <div className="space-y-1.5">
        <label htmlFor="provider-name" className="text-xs font-medium text-foreground">
          Provider Name
        </label>
        <Input
          id="provider-name"
          placeholder="Modal Gateway"
          value={formData.name}
          onChange={(e) => onChange((prev) => ({ ...prev, name: e.target.value }))}
          className="text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="provider-base-url" className="text-xs font-medium text-foreground">
          Base URL (OpenAI-compatible)
        </label>
        <Input
          id="provider-base-url"
          placeholder="https://fleet-proxy.modal.run/v1"
          value={formData.baseUrl}
          onChange={(e) => onChange((prev) => ({ ...prev, baseUrl: e.target.value }))}
          className="text-xs font-mono"
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="provider-api-key" className="text-xs font-medium text-foreground">
          API Key
        </label>
        <Input
          id="provider-api-key"
          type="password"
          placeholder="sk-..."
          value={formData.apiKey}
          onChange={(e) => onChange((prev) => ({ ...prev, apiKey: e.target.value }))}
          className="text-xs font-mono"
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="provider-model-id" className="text-xs font-medium text-foreground">
          Model ID (as your gateway names it, e.g. openai/gpt-4o-mini)
        </label>
        <Input
          id="provider-model-id"
          placeholder="openai/gpt-4o-mini"
          value={formData.modelId}
          onChange={(e) => onChange((prev) => ({ ...prev, modelId: e.target.value }))}
          className="text-xs font-mono"
        />
      </div>

      <div className="space-y-1.5">
        <span className="text-xs font-medium text-muted-foreground">
          Chat completion format:
        </span>
        <SegmentedOptions
          ariaLabel="Chat completion format"
          value="openai-chat-completions"
          options={[{ value: 'openai-chat-completions', label: 'OpenAI chat completions' }]}
          onChange={() => undefined}
        />
        <p className="text-[11px] text-muted-foreground">
          The engine's stable wire format; forward-compatible with DSPy's
          typed LMRequest/LMResponse API.
        </p>
      </div>

      <div className="space-y-1.5">
        <span className="text-xs font-medium text-muted-foreground">
          Response format:
        </span>
        <SegmentedOptions
          ariaLabel="Response format"
          value={formData.responseFormat}
          options={RESPONSE_FORMAT_OPTIONS}
          onChange={(responseFormat) => onChange((prev) => ({ ...prev, responseFormat }))}
        />
        <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
          <Cpu className="size-3" />
          Native function calling uses provider tool calls; JSON tool calls prompt tools as JSON for gateways without native support.
        </p>
      </div>

      <div className="space-y-1.5">
        <span className="text-xs font-medium text-muted-foreground">
          Messages format:
        </span>
        <SegmentedOptions
          ariaLabel="Messages format"
          value={formData.messagesFormat}
          options={MESSAGES_FORMAT_OPTIONS}
          onChange={(messagesFormat) => onChange((prev) => ({ ...prev, messagesFormat }))}
        />
        <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
          <MessageSquare className="size-3" />
          System role sends system messages as-is; developer role uses the newer developer role for OpenAI-style APIs.
        </p>
      </div>

      {error && <p className="text-[11px] text-destructive">{error}</p>}

      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCancel}
          className="text-xs"
        >
          Cancel
        </Button>
        <Button type="submit" size="sm" className="text-xs">
          Save Provider
        </Button>
      </div>
    </form>
  )
}
