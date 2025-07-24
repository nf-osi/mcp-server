(ns nfosi.prompts
  (:require [accent.registry :as registry]
            [cheshire.core :as json]
            [clj-http.client :as http]
            [clojure.java.io :as io]))


;; =============================================================================
;; Project management prompts
;; =============================================================================



;; =============================================================================
;; Curation prompts
;; =============================================================================

;; Agentic data curation / QC

(defn curate-dataset-in-synapse
  [{:keys [project_id]}]
  (let [dataset-schema-url "https://repo-prod.prod.sagebase.org/repo/v1/schema/type/registered/org.synapse.nf-portaldataset"
        dsp-url (str "https://dsp.nf.synapse.org/api/dsp/json/" project_id)]
    {:messages [{:role "user"
                 :content {:type "text"
                           :text (str "As my highly competent and responsible assistant, your goal is to curate datasets within a Synapse project, which means creating Dataset entities and creating metadata for them that complies with our model. " 
                                      ;; "and adding them to our staging dataset catalogue. " 
                                      "Review the folders and files in project " project_id ", any existing Datasets, and the data sharing plan for that project if it exists. " 
                                      "If it conceptually makes sense to create a dataset out of the group of files within a folder or set of folders, do so without unnecessary duplication of any existing Datasets. "
                                      "Referencing the data sharing plan during curation is helpful for further context and matching expectations with reality. "
                                      "Once you have a new Dataset entity, bind the JSON schema (also documented below) to it to facilitate organization-specific validation within our system. "
                                      "The newly returned Dataset entity is a table that allows you to query it to understand the content and formulate informative metadata. "
                                      "Once you have sufficient understanding, create and commit metadata for the Dataset that corresponds to our JSON schema. "
                                      "Always check that your metadata submission was deemed valid after committing and make revisions as needed. "
                                      "The definition of done is when all Datasets that conceptually makes sense have been created with valid metadata. "
                                      "During this process, feel free to bring up issues to my attention, ask about additional tools you may need, and consult me on complex edge cases. ")}}
                {:role "user"
                 :content {:type "resource"
                           :resource {:uri dataset-schema-url
                                      :text (slurp dataset-schema-url)}}}
                {:role "user"
                 :content {:type "resource"
                           :resource {:uri dsp-url
                                      :text (slurp dsp-url)}}}
                ]}))

(registry/defprompt :curate-dataset-in-synapse
  "Agentic workflow for curating datasets in Synapse"
  [{:name "project_id"
    :description "Synapse id for project"
    :required true}]
  :category #{}
  :permissions #{:read}
  :handler curate-dataset-in-synapse)

;; TODO: (defn curate-dataset-external)

;; (registry/defprompt :curate-dataset-external
;;  "Workflow for curating datasets outside of Synapse"