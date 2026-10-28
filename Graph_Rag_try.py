import os
from langchain_docling import DoclingLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter as RCTS
from langchain_ollama import ChatOllama
from langchain_neo4j import Neo4jGraph
from langchain_experimental.graph_transformers import LLMGraphTransformer

print("Loading Document")
loader =DoclingLoader("AGRICULTURE.pdf")
docs = loader.load()

print("Splitting text")
text_splitter = RCTS(chunk_size = 1000, chunk_overlap=100)
chunks = text_splitter.split_documents(docs)

llm = ChatOllama(model = "llama3.2", temperature =0)

print("Extracting graph entities")

transformer = LLMGraphTransformer(
llm = llm)

#transformer = LLMGraphTransformer(
#    llm=llm,
#    allowed_nodes=["Crop", "Disease", "Pest", "WeatherCondition", "Treatment", "SoilType"],
#    allowed_relationships=["AFFECTED_BY", "TREATED_WITH", "THRIVES_IN", "PREVENTS"]
#)
graph_documents = transformer.convert_to_graph_documents(chunks[20:30])

print("Pushing to neo4j")
graph = Neo4jGraph(
url = "bolt://localhost:7687",
username="neo4j",
password="password"
)

graph.add_graph_documents(graph_documents)

print("Graph extraction complete")
