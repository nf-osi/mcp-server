(ns nfosi.prompts
  (:require [accent.registry :as registry]
            [cheshire.core :as json]
            [clj-http.client :as http]
            [clojure.java.io :as io]))

;; =============================================================================
;; Curation prompts
;; =============================================================================

(defn annotate-dataset-handler
  "Handle dynamic prompt for the annotation workflow"
  [args]
  {:messages [{:role "user"
               :content {:type "text"
                         :text (str "Help me annotate the dataset " (:folder_id args) ". "
                                    "For context, I know that my data coordination center is" (:data_coordinating_center) ", which uses the specific configuration below. I may need help with selecting/setting some of the parameters.")}}
              {:role "user"
               :content {:type "resource"
                         :resource {:uri ""
                                    :text ""}}}
              {:role "assistant"
               :content {:type "text"
                         :text (str "In order to annotate a dataset, the first step is to generate a manifest for `folder_id` " (:folder_id args) " and refer to the DCC-specific configuration for parameters like `asset_view`. "
                                    "For `data_type`, to help infer the correct value for this dataset, I should check the data_type/template information and relations defined in the DCC data model, then try to understand the dataset, such as by looking at some examples or talking with the user more about the data. "
                                    "Occasionally, the data model is missing an appropriate template, in which case the best solution is to advise notifying admins for the DCC instead of using an incorrect template. "
                                    "I want to be confident about the manifest I generate for the user. "
                                    "If there is an issue when generating the manifest resource on the user's behalf, I should explain the error as clearly as possible. "
                                    "Let me attempt these actions now.")}}]})

(defprompt :annotate-dataset
  "Guided workflow for annotating a dataset"
  :arguments [{:name "folder_id" :description "Synapse id of the dataset folder" :required true}
              {:name "data_coordinating_center" :description "The data coordinating center (DCC) in which this workflow should be placed in context" :required true}
              ]
  :category #{:synapse}
  :permissions #{:read}
  :handler annotate-dataset-handler)


;; =============================================================================
;; Project management prompts
;; =============================================================================
  
;(defprompt :closeout-project-grant
;  "Close out a project following the NF SOP: 1. Read checklist 2. Get checkpoint report results 3. Go through project and generate artifacts for task items (e.g. updated manifests) 4. ")