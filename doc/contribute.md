# Contribution guide

## Adding tools

Tools provide additional functionality to the AI assistant (external APIs, local file access, knowledgebase, etc.).
Tools relevant and specific to NF work and research can be added to `src/nfosi/tools.clj`. 
Many general curation tools that work with Synapse should already be available via import from https://github.com/anngvu/accent. 

## Adding prompts

Prompts can be added to `src/nfosi/prompts.clj`. 
Prompts are meant for reusable workflows; many NF SOPs can be translated to prompts.
The existing examples demonstrate how to prompt thinking step-by-step and apply contextualized variables for certain workflows. 
When developing a prompt, one may realize it ideally uses a tool that is not yet available. In that case, implement the tool first.

## Adding resources

TODO
