(ns nfosi.prompts
  (:require [accent.registry :as registry]
            [cheshire.core :as json]
            [clj-http.client :as http]
            [clojure.java.io :as io]))


;; =============================================================================
;; Project/data management prompts
;; =============================================================================

(defn help-address-check-issues-handler 
  [{:keys [issue]}]
  (let [prod "https://raw.githubusercontent.com/Sage-Bionetworks/data_curator_config/refs/heads/prod/"
        config-url (str "NF-OSI/dca_config.json")]
    {:messages [{:role "user"
                 :content {:type "text"
                           :text (str "Please look at GitHub issue " issue ", which should contain information about and report with check results for a Synapse project. "
                                      "The report assesses datasets that need to pass metadata checks before they can be released as data artifacts and be usable in various apps/analysis downstream. "
                                      "As my assistant, focus on the latest report results to help me resolve any check issues: "
                                      "Review the report carefully to understand which datasets have complete and correct metadata, partial or incorrect metadata, or no metadata at all. " 
                                      "If you need to go through the Synapse project in addition to the report (and the tools are available), you can do so. "
                                      "For datasets with partial/incorrect metadata, generate a manifest using our below configuration, so you have a copy to use for review/corrections. "
                                      "Use our NF data model to research possible corrections, but create an issue in the data model repo if an update to the data model needs to be made to accommodate the dataset. "
                                      "If corrections are possible, show Python code that can be applied to correct the manifest. "
                                      "For datasets lacking metadata entirely, also generate a manifest with the appropriate template -- but for the data contributor to make the first pass at these. "
                                      "Lastly, compose a friendly email to the contributor summarizing the state of their metadata, any corrections you were able to make, links to all manifests you have prepared for them, and anything pertinent to the check. "
                                      "Let me know if you can't retrieve the GitHub resources because you don't have the tools available/lack permissions/report is missing. "
                                      "Also let me know if anything seems noteworthy or if I can provide additional context. ")}}
                 {:role "user"
                  :content {:type "resource"
                            :resource {:uri config-url
                                       :text (slurp config-url)}}}
                {:role "assistant"
                 :content {:type "text"
                           :text (str "The first step is to generate a metadata manifest for `folder_id` " folder_id ", assuming this is a qualifying Synapse folder. "
                                      "I will refer to the DCC-specific configuration for parameters like `asset_view`. "
                                      "To apply the `data_type` parameter for this dataset, I will reference the data types/templates defined in the DCC data model. "
                                      "Looking at the dataset, if its type is not clear, my protocol suggests that I try to confirm the type by interviewing you about the data or sampling some files (with your permission and if I have the tools available). "
                                      "Occasionally, the data model lacks coverage and doesn't define the appropriate template, in which case it's best to create an issue instead of using an incorrect template. "
                                      "I will not proceed if I am not confident about the manifest I can generate for you. "
                                      "Let me attempt this approach now.")}}]}))

(registry/defprompt :help-address-check-issues
  "Workflow for addressing items in project check report"
   [{:name "issue"
     :description "GitHub issue for project"
     :required true}]
   :category #{}
   :permissions #{:read}
   :handler help-address-check-issues-handler)


;; =============================================================================
;; Curation prompts
;; =============================================================================