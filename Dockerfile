FROM apache/nifi:1.28.1

USER root
ADD https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar /opt/nifi/nifi-current/lib/postgresql-42.7.4.jar
RUN chmod 644 /opt/nifi/nifi-current/lib/postgresql-42.7.4.jar
USER nifi
