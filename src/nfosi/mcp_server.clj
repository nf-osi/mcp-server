(ns nfosi.mcp-server
  (:gen-class)
  (:require [accent.state :refer [setup u]]
            [accent.registry :refer [tool-registry tools->mcp-format]]
            [accent.tools] ; Load accent's built-in, general tools
            [nfosi.tools] ; Load NF-only custom tools
            [curate.synapse :refer [new-syn]]
            [io.modelcontext.clojure-sdk.stdio-server :as io-server]
            [com.brunobonacci.mulog :as mu]))

(defn get-all-tools
  "Get all tools from the registry in MCP format"
  []
  (-> @tool-registry
      (tools->mcp-format)))

(def my-server-spec
  {:name "NF-OSI MCP Server"
   :version "1.0.0"
   :tools (get-all-tools)
   })

(defn -main
  [& args]
  ;; Initialize state
  (setup {:ui :external-client})
  (new-syn (@u :sat))
  (alter-var-root #'nfosi.tools/*schematic-auth-token*
                  (constantly (@u :sat)))

  ;; Start MCP server
  (let [server-id (random-uuid)]
    (mu/log ::my-mcp-server :info (str "Starting custom MCP server " server-id))
    @(io-server/run! (assoc my-server-spec :server-id server-id))))
