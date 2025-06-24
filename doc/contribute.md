# Contribution guide

## Adding tools

Tools provide additional functionality to the AI assistant (external APIs, local file access, knowledgebase, etc.).
Specialized NF work/research tools can be added to `src/nfosi/tools.clj`, where any current examples can also be viewed. 
To contribute, first create a https://github.com/nf-osi/mcp-server/labels/tool issue describing the tool concept, as comments can determine justification and refine the design to be more ergonomic. 
Note that some general Synapse/curation tools are already automatically available via [accent](https://github.com/anngvu/accent), while other tools should be provided by other MCP servers; 
for example, we absolutely use git tools for NF work, so for those tools it's better to compose [the official GitHub MCP-server](https://github.com/github/github-mcp-server). 
("Servers should be highly composable" is a philosophy in the [specification](https://modelcontextprotocol.io/specification/2025-03-26/architecture).)

## Adding prompts

Prompts are meant for more standardized and reusable workflows; in fact, many NF SOPs can be and should be translated to prompts. 
Prompts can be added to `src/nfosi/prompts.clj`, where any current examples can also be viewed. 
To contribute, first create a https://github.com/nf-osi/mcp-server/labels/prompt issue describing the prompt concept, as comments can help refine the prompt (perhaps even more so than for tools).

When developing a prompt, one may realize it ideally uses a tool that is not yet available. In that case, go through the tool contribution process as well.

## Adding resources

https://github.com/nf-osi/mcp-server/labels/resource contribution is similar to that for tools and prompts. 
