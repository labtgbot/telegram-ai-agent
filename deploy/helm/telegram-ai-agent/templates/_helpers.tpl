{{/*
Chart helpers — names, labels, image references, ingress class.
*/}}

{{- define "telegram-ai-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "telegram-ai-agent.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "telegram-ai-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Component-specific resource name.
Usage: include "telegram-ai-agent.componentName" (dict "ctx" . "name" "backend")
*/}}
{{- define "telegram-ai-agent.componentName" -}}
{{- $ctx := .ctx -}}
{{- printf "%s-%s" (include "telegram-ai-agent.fullname" $ctx) .name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels shared by all rendered resources.
*/}}
{{- define "telegram-ai-agent.labels" -}}
helm.sh/chart: {{ include "telegram-ai-agent.chart" . }}
{{ include "telegram-ai-agent.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: telegram-ai-agent
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "telegram-ai-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "telegram-ai-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Selector labels for an individual component (so each Deployment/Service
targets only its own pods).
*/}}
{{- define "telegram-ai-agent.componentSelectorLabels" -}}
{{- $ctx := .ctx -}}
{{ include "telegram-ai-agent.selectorLabels" $ctx }}
app.kubernetes.io/component: {{ .name }}
{{- end -}}

{{- define "telegram-ai-agent.componentLabels" -}}
{{- $ctx := .ctx -}}
{{ include "telegram-ai-agent.labels" $ctx }}
app.kubernetes.io/component: {{ .name }}
{{- end -}}

{{/*
Resolve an image reference for a component.
Inputs:
  ctx        — root context
  component  — component key (backend|worker|miniApp|admin)
*/}}
{{- define "telegram-ai-agent.image" -}}
{{- $ctx := .ctx -}}
{{- $component := .component -}}
{{- $img := index $ctx.Values $component "image" -}}
{{- $tag := default $ctx.Values.image.tag $img.tag -}}
{{- if not $tag -}}
{{- $tag = $ctx.Chart.AppVersion -}}
{{- end -}}
{{- printf "%s/%s:%s" (trimSuffix "/" $ctx.Values.image.registry) $img.repository $tag -}}
{{- end -}}

{{/*
Image pull secrets fragment.
*/}}
{{- define "telegram-ai-agent.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end -}}
{{- end -}}

{{/*
Ingress className with fallback.
*/}}
{{- define "telegram-ai-agent.ingressClassName" -}}
{{- default .Values.ingressClassName .Values.ingress.className -}}
{{- end -}}

{{/*
Host-specific ingress resource name.
*/}}
{{- define "telegram-ai-agent.ingressHostName" -}}
{{- $ctx := .ctx -}}
{{- $safeHost := regexReplaceAll "[^a-z0-9-]+" (lower .host) "-" -}}
{{- $safeHost = trimAll "-" $safeHost -}}
{{- printf "%s-%s" (include "telegram-ai-agent.fullname" $ctx) $safeHost | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
ServiceAccount name for backend.
*/}}
{{- define "telegram-ai-agent.backend.serviceAccountName" -}}
{{- if .Values.backend.serviceAccount.create -}}
{{- default (include "telegram-ai-agent.componentName" (dict "ctx" . "name" "backend")) .Values.backend.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.backend.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
API prefix shared by admin dashboard helper defaults.
*/}}
{{- define "telegram-ai-agent.apiPrefix" -}}
{{- default "/api/v1" .Values.config.API_V1_PREFIX -}}
{{- end -}}

{{/*
Server-side admin API base URL. Defaults to the release-local backend Service.
*/}}
{{- define "telegram-ai-agent.admin.apiBaseUrl" -}}
{{- $configured := trimSuffix "/" (toString (default "" .Values.admin.apiBaseUrl)) -}}
{{- if $configured -}}
{{- $configured -}}
{{- else -}}
{{- printf "http://%s:%v%s" (include "telegram-ai-agent.componentName" (dict "ctx" . "name" "backend")) .Values.backend.service.port (include "telegram-ai-agent.apiPrefix" .) -}}
{{- end -}}
{{- end -}}

{{/*
Browser-visible admin API base URL. Defaults to the public backend ingress host.
*/}}
{{- define "telegram-ai-agent.admin.publicApiBaseUrl" -}}
{{- $configured := trimSuffix "/" (toString (default "" .Values.admin.publicApiBaseUrl)) -}}
{{- if $configured -}}
{{- $configured -}}
{{- else -}}
{{- $backendHost := "" -}}
{{- if .Values.ingress.enabled -}}
{{- range $host := .Values.ingress.hosts -}}
{{- $servesBackend := false -}}
{{- range $path := $host.paths -}}
{{- if eq $path.service "backend" -}}
{{- $servesBackend = true -}}
{{- end -}}
{{- end -}}
{{- if and $servesBackend (not $backendHost) -}}
{{- $backendHost = $host.host -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if $backendHost -}}
{{- $scheme := ternary "https" "http" .Values.ingress.tls.enabled -}}
{{- printf "%s://%s%s" $scheme $backendHost (include "telegram-ai-agent.apiPrefix" .) -}}
{{- end -}}
{{- end -}}
{{- end -}}
