# Model Context Protocol (MCP) Server for NF-OSI

An MCP server that gives your AI assistant access NF-OSI resources and tools. 
This builds on top of [accent](https://github.com/anngvu/accent) so Synapse tools are already included; don't add *accent* to your configuration if you use this server.

## Pairings

This is likely only one of multiple servers that would be added to your configuration.
**To be productive, your AI assistant would need to have access to the other tools already integral in your day-to-day NF work, which at minimum are:**  

- git/GitHub with [GitHub's official MCP server](https://github.com/github/github-mcp-server)
- Jira with [Jira's official MCP server](https://support.atlassian.com/rovo/docs/getting-started-with-the-atlassian-remote-mcp-server/)
