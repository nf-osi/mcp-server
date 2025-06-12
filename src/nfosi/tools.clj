(ns nfosi.tools
  (:require [accent.registry :as registry]
            [cheshire.core :as json]
            [clj-http.client :as http]
            [clojure.java.io :as io]))

;; =============================================================================
;; Schematic tools
;; =============================================================================

;; Configuration
(def ^:dynamic *schematic-api-base-url* "http://schematic.api.sagebionetworks.org/v1")
(def ^:dynamic *auth-token* nil)

(defn make-api-request
  "Helper function to make HTTP requests to the Schematic API"
  [method endpoint params & {:keys [multipart-data]}]
  (try
    (let [url (str *schematic-api-base-url* endpoint)
          headers (cond-> {"Content-Type" "application/json"}
                    *auth-token* (assoc "Authorization" (str "Bearer " *auth-token*)))
          request-opts (cond-> {:headers headers
                                :throw-exceptions false}
                         (= method :get) (assoc :query-params params)
                         (= method :post) (assoc :query-params params)
                         multipart-data (assoc :multipart multipart-data))]
      (let [response (case method
                       :get (http/get url request-opts)
                       :post (http/post url request-opts))]
        (if (<= 200 (:status response) 299)
          {:type "text"
           :text (or (:body response) "Success")}
          {:type "text"
           :text (str "API Error: " (:status response) " - " (:body response))
           :isError true})))
    (catch Exception e
      {:type "text"
       :text (str "Request failed: " (.getMessage e))
       :isError true})))

;; /manifest/generate

(defn generate-manifest-handler
  [{:keys [schema_url title data_type use_annotations dataset_id asset_view
           output_format strict_validation data_model_labels]}]
  (let [params (cond-> {"schema_url" schema_url
                        "data_type" (if (vector? data_type) data_type [data_type])}
                 title (assoc "title" title)
                 use_annotations (assoc "use_annotations" use_annotations)
                 dataset_id (assoc "dataset_id" (if (vector? dataset_id) dataset_id [dataset_id]))
                 asset_view (assoc "asset_view" asset_view)
                 output_format (assoc "output_format" output_format)
                 strict_validation (assoc "strict_validation" strict_validation)
                 data_model_labels (assoc "data_model_labels" data_model_labels))]
    (make-api-request :get "/manifest/generate" params)))

(registry/deftool :generate-manifest
  "Generate metadata manifest files for a given data model and component(s)"
  {:type "object"
   :properties {"schema_url" {:type "string"
                              :description "Data Model URL (e.g. https://raw.githubusercontent.com/Sage-Bionetworks/schematic/develop/tests/data/example.model.jsonld)"}
                "title" {:type "string"
                         :description "Title of Manifest or Title Prefix, if making multiple manifests"}
                "data_type" {:type "array"
                             :items {:type "string"}
                             :description "Data Model Component(s). To make all manifests, enter [\"all manifests\"]"}
                "use_annotations" {:type "boolean"
                                   :default false
                                   :description "To Use Annotations"}
                "dataset_id" {:type "array"
                              :items {:type "string"}
                              :description "Dataset ID(s). If getting existing manifest, this should be parent ID of the manifest"}
                "asset_view" {:type "string"
                              :description "ID of view listing all project data assets (e.g. Synapse fileview ID)"}
                "output_format" {:type "string"
                                 :enum ["excel" "google_sheet" "dataframe (only if getting existing manifests)"]
                                 :description "Output format for the manifest"}
                "strict_validation" {:type "boolean"
                                     :default true
                                     :description "Strictness of Google Sheets regex validation (Google Sheets only)"}
                "data_model_labels" {:type "string"
                                     :enum ["display_label" "class_label"]
                                     :default "class_label"
                                     :description "How to set labels in the data model"}}
   :required ["schema_url" "data_type"]}
  :category #{:schematic :manifest}
  :permissions #{:read}
  :handler generate-manifest-handler)

;; /model/submit

(defn submit-manifest-handler
  [{:keys [schema_url data_model_labels data_type dataset_id manifest_record_type
           restrict_rules hide_blanks asset_view json_str table_manipulation
           table_column_names annotation_keys file_annotations_upload
           project_scope dataset_scope file_path]}]
  (let [params (cond-> {"schema_url" schema_url
                        "dataset_id" dataset_id
                        "restrict_rules" (boolean restrict_rules)
                        "asset_view" asset_view}
                 data_model_labels (assoc "data_model_labels" data_model_labels)
                 data_type (assoc "data_type" data_type)
                 manifest_record_type (assoc "manifest_record_type" manifest_record_type)
                 hide_blanks (assoc "hide_blanks" hide_blanks)
                 json_str (assoc "json_str" json_str)
                 table_manipulation (assoc "table_manipulation" table_manipulation)
                 table_column_names (assoc "table_column_names" table_column_names)
                 annotation_keys (assoc "annotation_keys" annotation_keys)
                 file_annotations_upload (assoc "file_annotations_upload" file_annotations_upload)
                 project_scope (assoc "project_scope" project_scope)
                 dataset_scope (assoc "dataset_scope" dataset_scope))
        multipart-data (when file_path
                         [{:name "file_name"
                           :content (io/file file_path)}])]
    (make-api-request :post "/model/submit" params :multipart-data multipart-data)))

(registry/deftool :submit-manifest
  "Submit annotated manifest files to validate and store in Synapse"
  {:type "object"
   :properties {"schema_url" {:type "string"
                              :description "Data Model URL"}
                "data_model_labels" {:type "string"
                                     :enum ["display_label" "class_label"]
                                     :default "class_label"
                                     :description "How to set labels in the data model"}
                "data_type" {:type "string"
                             :description "Data Model Component (e.g. 'Patient')"}
                "dataset_id" {:type "string"
                              :description "Dataset SynID where manifest will be stored"}
                "manifest_record_type" {:type "string"
                                        :enum ["file_only" "file_and_entities" "table_and_file" "table_file_and_entities"]
                                        :description "How to store the manifest in Synapse"}
                "restrict_rules" {:type "boolean"
                                  :default false
                                  :description "If true, only use in-house validation rules; if false, use Great Expectations"}
                "hide_blanks" {:type "boolean"
                               :description "Hide annotations with blank values from Synapse dataset"}
                "asset_view" {:type "string"
                              :description "ID of view listing all project data assets"}
                "json_str" {:type "string"
                            :description "JSON string representation of manifest data"}
                "table_manipulation" {:type "string"
                                      :enum ["replace" "upsert"]
                                      :description "How to handle existing tables with same name"}
                "table_column_names" {:type "string"
                                      :enum ["display_name" "display_label" "class_label"]
                                      :default "class_label"
                                      :description "Format for table column names"}
                "annotation_keys" {:type "string"
                                   :enum ["display_label" "class_label"]
                                   :default "class_label"
                                   :description "Format for annotation keys"}
                "file_annotations_upload" {:type "boolean"
                                           :default true
                                           :description "Whether to add annotations when submitting file-based manifests"}
                "project_scope" {:type "array"
                                 :items {:type "string"}
                                 :description "Subset of projects within asset view relevant for operation"}
                "dataset_scope" {:type "string"
                                 :description "Dataset to validate against for filename validation"}
                "file_path" {:type "string"
                             :description "Local path to manifest file (CSV or JSON) to upload"}}
   :required ["schema_url" "dataset_id" "restrict_rules" "asset_view"]}
  :category #{:schematic :manifest :validation}
  :permissions #{:write}
  :handler submit-manifest-handler)

;; /model/validate

(defn validate-manifest-handler
  [{:keys [schema_url data_type data_model_labels restrict_rules json_str
           asset_view project_scope dataset_scope file_path]}]
  (let [params (cond-> {"schema_url" schema_url
                        "data_type" data_type}
                 data_model_labels (assoc "data_model_labels" data_model_labels)
                 restrict_rules (assoc "restrict_rules" restrict_rules)
                 json_str (assoc "json_str" json_str)
                 asset_view (assoc "asset_view" asset_view)
                 project_scope (assoc "project_scope" project_scope)
                 dataset_scope (assoc "dataset_scope" dataset_scope))
        multipart-data (when file_path
                         [{:name "file_name"
                           :content (io/file file_path)}])]
    (make-api-request :post "/model/validate" params :multipart-data multipart-data)))

(registry/deftool :validate-manifest
  "Validate metadata manifest files against a data model"
  {:type "object"
   :properties {"schema_url" {:type "string"
                              :description "Data Model URL"}
                "data_type" {:type "string"
                             :description "Data Model Component to validate against"}
                "data_model_labels" {:type "string"
                                     :enum ["display_label" "class_label"]
                                     :default "class_label"
                                     :description "How to set labels in the data model"}
                "restrict_rules" {:type "boolean"
                                  :default false
                                  :description "If true, only use in-house validation rules; if false, use Great Expectations"}
                "json_str" {:type "string"
                            :description "JSON string representation of manifest data to validate"}
                "asset_view" {:type "string"
                              :description "ID of view listing all project data assets (required for cross-manifest validation)"}
                "project_scope" {:type "array"
                                 :items {:type "string"}
                                 :description "Subset of projects within asset view relevant for validation"}
                "dataset_scope" {:type "string"
                                 :description "Dataset to validate against for filename validation"}
                "file_path" {:type "string"
                             :description "Local path to manifest file (CSV or JSON) to validate"}}
   :required ["schema_url" "data_type"]}
  :category #{:schematic :manifest :validation}
  :permissions #{:read}
  :handler validate-manifest-handler)
