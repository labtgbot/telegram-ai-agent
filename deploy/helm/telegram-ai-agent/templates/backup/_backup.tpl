{{/*
Shared bits for backup CronJobs.

Render the standard envFrom, image, securityContext, etc. once and reuse
across every backup CronJob.
*/}}

{{- define "telegram-ai-agent.backup.serviceAccountName" -}}
{{- if .Values.backup.serviceAccount.create -}}
{{- default (include "telegram-ai-agent.componentName" (dict "ctx" . "name" "backup")) .Values.backup.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.backup.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "telegram-ai-agent.backup.image" -}}
{{- $img := .Values.backup.image -}}
{{- $tag := default .Values.image.tag $img.tag -}}
{{- if not $tag -}}
{{- $tag = .Chart.AppVersion -}}
{{- end -}}
{{- printf "%s/%s:%s" (trimSuffix "/" .Values.image.registry) $img.repository $tag -}}
{{- end -}}

{{/*
Shared envFrom block — pulls AWS creds / passwords / webhook from the backup
Secret; bucket / KMS / retention come from a small dedicated ConfigMap so
operators can `kubectl edit cm` without bouncing the Helm release.
*/}}
{{- define "telegram-ai-agent.backup.envFrom" -}}
- configMapRef:
    name: {{ include "telegram-ai-agent.componentName" (dict "ctx" . "name" "backup-config") }}
- secretRef:
    name: {{ .Values.backup.secret.name }}
{{- end -}}

{{- define "telegram-ai-agent.backup.podSpec" -}}
serviceAccountName: {{ include "telegram-ai-agent.backup.serviceAccountName" . }}
{{- include "telegram-ai-agent.imagePullSecrets" . | nindent 0 }}
restartPolicy: OnFailure
securityContext:
  runAsNonRoot: true
  runAsUser: 65534
  fsGroup: 65534
  seccompProfile:
    type: RuntimeDefault
{{- end -}}
