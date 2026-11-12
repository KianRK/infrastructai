{{- define "roadscan.labels" -}}
app.kubernetes.io/part-of: roadscan
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/* Image reference: [registry/]repository:tag */}}
{{- define "roadscan.image" -}}
{{- $tag := required "image.tag is required" .root.Values.image.tag -}}
{{- with .root.Values.image.registry }}{{ . }}/{{ end }}{{ .repository }}:{{ $tag }}
{{- end }}

{{- define "roadscan.secretsDir" -}}/mnt/secrets{{- end }}

{{/* Fails the installation early on inconsistent values. */}}
{{- define "roadscan.validate" -}}
{{- if and .Values.tls.enabled (not .Values.host) }}
{{- fail "host is required when tls.enabled is true" }}
{{- end }}
{{- if not (has .Values.secrets.source (list "keyVault" "kubernetesSecret")) }}
{{- fail "secrets.source must be keyVault or kubernetesSecret" }}
{{- end }}
{{- if eq .Values.secrets.source "keyVault" }}
{{- $_ := required "secrets.keyVault.name is required" .Values.secrets.keyVault.name }}
{{- $_ := required "secrets.keyVault.tenantId is required" .Values.secrets.keyVault.tenantId }}
{{- $_ := required "serviceAccount.workloadIdentityClientId is required to read Key Vault" .Values.serviceAccount.workloadIdentityClientId }}
{{- end }}
{{- if not (has .Values.ray.upgrade (list "InPlace" "NewCluster")) }}
{{- fail "ray.upgrade must be InPlace or NewCluster" }}
{{- end }}
{{- if and (hasPrefix "models:/" (default "" .Values.serve.detector.model_uri)) (not .Values.serve.mlflowTrackingUri) }}
{{- fail "serve.mlflowTrackingUri is required for a models:/ detector URI" }}
{{- end }}
{{- if and (hasPrefix "models:/" (default "" .Values.serve.traffic.model_uri)) (not .Values.serve.mlflowTrackingUri) }}
{{- fail "serve.mlflowTrackingUri is required for a models:/ traffic detector URI" }}
{{- end }}
{{- $cpus := addf .Values.serve.cpus.api .Values.serve.cpus.detector .Values.serve.cpus.describer .Values.serve.cpus.traffic }}
{{- if gt $cpus (float64 .Values.ray.head.numCpus) }}
{{- fail (printf "serve.cpus add up to %v, more than ray.head.numCpus (%v)" $cpus .Values.ray.head.numCpus) }}
{{- end }}
{{- end }}

{{/* The Ray cluster definition, also hashed to detect changes that need new pods. */}}
{{- define "roadscan.rayClusterConfig" -}}
rayVersion: {{ .Values.ray.version | quote }}
headGroupSpec:
  rayStartParams:
    num-cpus: {{ .Values.ray.head.numCpus | quote }}
    object-store-memory: {{ mul (.Values.ray.head.objectStoreMemoryMi | int64) 1048576 | quote }}
    dashboard-host: 0.0.0.0
  template:
    metadata:
      labels:
        {{- include "roadscan.labels" . | nindent 8 }}
        app.kubernetes.io/name: roadscan-serving
        {{- if .Values.serviceAccount.workloadIdentityClientId }}
        azure.workload.identity/use: "true"
        {{- end }}
    spec:
      serviceAccountName: {{ .Values.serviceAccount.name }}
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 100
        fsGroup: 100
        seccompProfile:
          type: RuntimeDefault
      {{- with .Values.ray.head.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.ray.head.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: ray-head
          image: {{ include "roadscan.image" (dict "root" . "repository" .Values.image.serving.repository) }}
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - { name: gcs, containerPort: 6379 }
            - { name: dashboard, containerPort: 8265 }
            - { name: client, containerPort: 10001 }
            - { name: serve, containerPort: 8000 }
          {{- with .Values.serve.mlflowTrackingUri }}
          env:
            - name: MLFLOW_TRACKING_URI
              value: {{ . | quote }}
          {{- end }}
          resources:
            {{- toYaml .Values.ray.head.resources | nindent 12 }}
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: [ALL]
          volumeMounts:
            - name: secrets
              mountPath: {{ include "roadscan.secretsDir" . }}
              readOnly: true
            - name: shm
              mountPath: /dev/shm
            - name: ray-tmp
              mountPath: /tmp/ray
      volumes:
        - name: secrets
          {{- if eq .Values.secrets.source "keyVault" }}
          csi:
            driver: secrets-store.csi.k8s.io
            readOnly: true
            volumeAttributes:
              secretProviderClass: {{ .Release.Name }}-secrets
          {{- else }}
          secret:
            secretName: {{ .Values.secrets.kubernetesSecret.name }}
            defaultMode: 0440
          {{- end }}
        # Ray's object store; without it Ray falls back to slower disk-backed memory.
        - name: shm
          emptyDir:
            medium: Memory
            # Written the way Kubernetes normalises quantities, or the next upgrade conflicts
            # with the value as stored by the operator.
            sizeLimit: {{ add (.Values.ray.head.objectStoreMemoryMi | int64) 128 }}Mi
        - name: ray-tmp
          emptyDir: {}
{{- end }}
