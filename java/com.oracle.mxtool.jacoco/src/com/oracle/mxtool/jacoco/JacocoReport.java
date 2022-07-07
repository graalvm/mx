/*
 * Copyright (c) 2012, 2017, Oracle and/or its affiliates. All rights reserved.
 * DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
 *
 * This code is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License version 2 only, as
 * published by the Free Software Foundation.  Oracle designates this
 * particular file as subject to the "Classpath" exception as provided
 * by Oracle in the LICENSE file that accompanied this code.
 *
 * This code is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
 * version 2 for more details (a copy is included in the LICENSE file that
 * accompanied this code).
 *
 * You should have received a copy of the GNU General Public License version
 * 2 along with this work; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
 *
 * Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
 * or visit www.oracle.com if you need additional information or have any
 * questions.
 */
package com.oracle.mxtool.jacoco;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IBundleCoverage;
import org.jacoco.core.analysis.ICoverageVisitor;
import org.jacoco.core.data.ExecutionDataReader;
import org.jacoco.core.data.ExecutionDataStore;
import org.jacoco.core.data.SessionInfoStore;
import org.jacoco.report.FileMultiReportOutput;
import org.jacoco.report.IReportGroupVisitor;
import org.jacoco.report.IReportVisitor;
import org.jacoco.report.InputStreamSourceFileLocator;
import org.jacoco.report.html.HTMLFormatter;
import org.jacoco.report.xml.XMLFormatter;
import org.objectweb.asm.ClassReader;

import com.oracle.mxtool.jacoco.lcov.LcovFormatter;

import joptsimple.ArgumentAcceptingOptionSpec;
import joptsimple.NonOptionArgumentSpec;
import joptsimple.OptionException;
import joptsimple.OptionParser;
import joptsimple.OptionSet;

public class JacocoReport {
    private final List<String> excludes;
    private final ExecutionDataStore executionDataStore;
    private final SessionInfoStore sessionInfoStore;

    public JacocoReport(List<String> excludes) {
        executionDataStore = new ExecutionDataStore();
        sessionInfoStore = new SessionInfoStore();
        // @formatter:off
        this.excludes = excludes.stream()
                        .map(s -> s.endsWith(".*") ? s.substring(0, s.length() - 2) : s)
                        .map(s -> s.replace('.', '/'))
                        .collect(Collectors.toList());
        // @formatter:on
    }

    /**
     * Project specification.
     */
    public static class ProjectSpec {
        private final File projectDir;
        private final File binDir;
        private final File[] srcDirs;

        /**
         * @param spec a specification string in the form "project-dir:binary-dir".
         */
        public ProjectSpec(String spec) {
            String[] s = spec.split(":");
            if (s.length < 2) {
                throw new RuntimeException(String.format("Unsupported project specification: %s", spec));
            }
            this.projectDir = new File(s[0]);
            this.binDir = new File(s[1]);

            srcDirs = new File[s.length - 2];
            for (int i = 2; i < s.length; i++) {
                srcDirs[i - 2] = new File(s[i]);
            }
        }
    }

    public static void main(String... args) throws IOException {
        OptionParser parser = new OptionParser();
        ArgumentAcceptingOptionSpec<File> inputsSpec = parser.accepts("in", "Input coverage file produced by JaCoCo").withRequiredArg().ofType(File.class).required();
        NonOptionArgumentSpec<ProjectSpec> projectsSpec = parser.nonOptions("The project directories to analyse").ofType(ProjectSpec.class);
        ArgumentAcceptingOptionSpec<File> outSpec = parser.accepts("out").withRequiredArg().ofType(File.class).defaultsTo(new File("coverage"));
        ArgumentAcceptingOptionSpec<String> formatSpec = parser.accepts("format").withRequiredArg().ofType(String.class).defaultsTo("html");
        ArgumentAcceptingOptionSpec<File> excludeFile = parser.accepts("exclude-file").withOptionalArg().ofType(File.class);

        OptionSet options;
        try {
            options = parser.parse(args);
        } catch (OptionException e) {
            System.err.println(e.getMessage());
            parser.printHelpOn(System.err);
            return;
        }

        if (!options.has(projectsSpec) || options.valuesOf(projectsSpec).isEmpty()) {
            System.err.println("Project directories are required");
            parser.printHelpOn(System.err);
            return;
        }

        List<String> excludes;
        File excludeOptionValue = options.valueOf(excludeFile);
        if (excludeOptionValue == null) {
            excludes = Collections.emptyList();
        } else {
            excludes = Files.readAllLines(excludeOptionValue.toPath());
        }
        new JacocoReport(excludes).makeReport(options.valueOf(outSpec), options.valuesOf(projectsSpec), options.valuesOf(inputsSpec), options.valueOf(formatSpec));
    }

    public void makeReport(File reportDirectory, List<ProjectSpec> projects, List<File> execDatas, String format) throws IOException {
        for (File execData : execDatas) {
            System.out.print("Loading '" + execData.getName() + "'... ");
            loadExecutionData(execData);
            System.out.println("OK");
        }
        List<BundleAndProject> bundles = new ArrayList<>(projects.size());
        for (ProjectSpec project : projects) {
            System.out.print("Analyzing project '" + project.projectDir + "'... ");
            bundles.add(new BundleAndProject(analyseProject(project.binDir, project.projectDir.getName()), project.srcDirs));
            System.out.println("OK");
        }
        switch (format) {
            case "html":
                System.out.print("Creating HTML report... ");
                createHtmlReport(reportDirectory, bundles);
                System.out.println("OK");
                break;
            case "xml":
                System.out.print("Creating XML report... ");
                createXmlReport(reportDirectory, bundles);
                System.out.println("OK");
                break;
            case "lcov":
                System.out.print("Creating LCOV report... ");
                createLcovReport(reportDirectory, bundles);
                System.out.println("OK");
                break;
            default:
                System.err.println("Unsupported format: " + format);
                break;
        }
    }

    private static class BundleAndProject {
        final IBundleCoverage bundle;
        final File[] srcDirs;

        BundleAndProject(IBundleCoverage bundle, File[] srcDirs) {
            this.bundle = bundle;
            this.srcDirs = srcDirs;
        }

        @Override
        public String toString() {
            return bundle.toString();
        }
    }

    public void loadExecutionData(File f) throws IOException {
        final FileInputStream fis = new FileInputStream(f);
        final ExecutionDataReader executionDataReader = new ExecutionDataReader(fis);

        executionDataReader.setExecutionDataVisitor(executionDataStore);
        executionDataReader.setSessionInfoVisitor(sessionInfoStore);

        while (executionDataReader.read()) {
            // Read all data
        }

        fis.close();
    }

    public static class MultiDirectorySourceFileLocator extends InputStreamSourceFileLocator {
        private final File[] directories;

        protected MultiDirectorySourceFileLocator(String encoding, int tabWidth, File... directories) {
            super(encoding, tabWidth);
            this.directories = directories;
        }

        @Override
        protected InputStream getSourceStream(String path) throws IOException {
            for (File directory : directories) {
                final File file = new File(directory, path);
                if (file.exists()) {
                    return new FileInputStream(file);
                }
            }
            return null;
        }

        public String getSourceFilePath(String packageName, String fileName) {
            final String filename = fileName.replace("\\", File.separator).replace("/", File.separator);
            final String packagename = packageName.replace("/", File.separator);

            if (!Paths.get(filename).isAbsolute()) {
                for (File directory : directories) {
                    final File fileWithPackage = new File(directory, packagename + File.separator + filename);
                    if (fileWithPackage.exists()) {
                        return fileWithPackage.toPath().toString();
                    }

                    final File file = new File(directory, filename);
                    if (file.exists()) {
                        return file.toPath().toString();
                    }
                }
            }
            return null;
        }
    }

    public void createHtmlReport(File reportDirectory, List<BundleAndProject> bundleAndProjects) throws IOException {
        final HTMLFormatter htmlFormatter = new HTMLFormatter();
        final IReportVisitor visitor = htmlFormatter.createVisitor(new FileMultiReportOutput(reportDirectory));
        executeReportVisitor(bundleAndProjects, visitor);
    }

    public void createXmlReport(File reportDirectory, List<BundleAndProject> bundleAndProjects) throws IOException {
        final XMLFormatter htmlFormatter = new XMLFormatter();
        final IReportVisitor visitor = htmlFormatter.createVisitor(new FileOutputStream(reportDirectory.getAbsolutePath() + File.separator + "jacoco.xml"));
        executeReportVisitor(bundleAndProjects, visitor);
    }

    public void createLcovReport(File reportDirectory, List<BundleAndProject> bundleAndProjects) throws IOException {
        final LcovFormatter lcovFormatter = new LcovFormatter();
        Path reportPath = reportDirectory.getAbsoluteFile().toPath().resolve("lcov.info");
        Files.createDirectories(reportDirectory.toPath());
        final IReportVisitor visitor = lcovFormatter.createVisitor(Files.newOutputStream(reportPath));
        executeReportVisitor(bundleAndProjects, visitor);
    }

    private void executeReportVisitor(List<BundleAndProject> bundleAndProjects, IReportVisitor visitor) throws IOException {
        visitor.visitInfo(sessionInfoStore.getInfos(), executionDataStore.getContents());
        IReportGroupVisitor group = visitor.visitGroup("Graal");
        for (BundleAndProject bundleAndProject : bundleAndProjects) {
            group.visitBundle(bundleAndProject.bundle, new MultiDirectorySourceFileLocator("utf-8", 4, bundleAndProject.srcDirs));
        }

        visitor.visitEnd();
    }

    private class JaCoCoAnalyzer extends Analyzer {

        JaCoCoAnalyzer(ExecutionDataStore executionData, ICoverageVisitor coverageVisitor) {
            super(executionData, coverageVisitor);
        }

        @Override
        public void analyzeClass(byte[] buffer, String location) throws IOException {
            final ClassReader reader = new ClassReader(buffer);
            if (!isClassExcluded(reader.getClassName())) {
                super.analyzeClass(buffer, location);
            }
        }
    }

    private boolean isClassExcluded(String className) {
        for (String excludePattern : excludes) {
            if (className.startsWith(excludePattern)) {
                return true;
            }
        }
        return false;
    }

    public IBundleCoverage analyseProject(File project, String name) throws IOException {
        final CoverageBuilder coverageBuilder = new CoverageBuilder();
        final Analyzer analyzer = new JaCoCoAnalyzer(executionDataStore, coverageBuilder);

        analyzer.analyzeAll(project);

        return coverageBuilder.getBundle(name);
    }
}
