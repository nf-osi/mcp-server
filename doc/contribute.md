# Contribution guide

## Adding tools

Tools provide additional functionality to the AI assistant (external APIs, local file access, knowledgebase, etc.).
Tools can be added to `src/nfosi/tools.clj`, though only tools relevant and specific to NF work and research should be implemented. 
For example, a subset of NF publications are compiled for the knowledgebase. 
Other general curation tools that work with Synapse should already be available via import from https://github.com/anngvu/accent. 
Even more general tools (such as ability to access Google Drive) should depend on complementary MCP servers (because MCP servers are meant to be composable).

## Adding prompts

Prompts can be added to `src/nfosi/prompts.clj`. 
Prompts are meant for reusable workflows. For example, many NF SOPs can be translated to prompts.
The existing code demonstrate how to prompt thinking step-by-step and apply contextualized variables for certain workflows. 
When developing a prompt, one may realize it ideally uses a tool that is not yet available. In that case, implement the tool first.

## Adding resources

TODO
