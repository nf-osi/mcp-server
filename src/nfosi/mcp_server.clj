(ns nfosi.mcp-server
  (:gen-class)
  (:require [accent.state :refer [setup u]]
            [accent.registry :refer [tool-registry tools->mcp-format]]
            [accent.tools] ; Load accent's built-in, general tools
            [nfosi.tools] ; Load NF-only custom tools
            [curate.synapse :refer [new-syn]]
            [io.modelcontext.clojure-sdk.stdio-server :as io-server]
            ;[com.brunobonacci.mulog :as mu]
            ))

(def all-tools
  (-> @tool-registry
      (tools->mcp-format)))

(def nfosi-server-spec
  {:name "NF-OSI MCP Server"
   :version "0.1.0"
   :tools all-tools
   })

(defn -main
  [& args]
  ;; Initialize state
  (setup {:ui :external-client})
  (new-syn (@u :sat))

  ;; Start MCP server
  (let [server-id (random-uuid)]
    ;;(mu/log ::nfosi-mcp-server :info (str "Starting NF-OSI MCP server " server-id))
    @(io-server/run! (assoc nfosi-server-spec :server-id server-id))))
