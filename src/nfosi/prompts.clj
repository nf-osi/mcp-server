(ns nfosi.tools
  (:require [accent.registry :as registry]
            [cheshire.core :as json]
            [clj-http.client :as http]
            [clojure.java.io :as io]))

;; =============================================================================
;; Curation prompts
;; =============================================================================


(defprompt :annotate-dataset
  "Annotate dataset"
  :arguments [{:name "folder_id" :description "Synapse id of the dataset folder" :required true}
              ;; {:name "dcc" :description "DCC context" :required true}
              ]
  :category #{:synapse}
  :permissions #{:read}

  :handler (fn [args] 
             {:messages [{:role "assistant" 
                          :content {:type "text" 
                                    :text (str "In order to annotate the mentioned dataset, I need to generate a manifest with" (:folder_id args) "as the `dataset_id` and syn16858331 as the `asset_view`."
                                               ;"To understand what to use for the `data_type` parameter, I should see some example files within this dataset, then use known data_type <-> template mappings in the data model."
                                               ;"Sometimes the data model is missing an appropriate template, in which case the best solution is to advise notifying admins at nfosi@sagebionetworks instead of using an incorrect template."
                                               ;"But if I can confidently generate a template, I will get a link to a Googlesheet that can be filled out."
                                               "Let me attempt this now.")}}]})
)
  