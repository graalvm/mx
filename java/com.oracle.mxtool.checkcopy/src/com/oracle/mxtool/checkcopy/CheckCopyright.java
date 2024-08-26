/*
 * Copyright (c) 2011, 2021, Oracle and/or its affiliates. All rights reserved.
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
package com.oracle.mxtool.checkcopy;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URISyntaxException;
import java.net.URL;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Calendar;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.Future;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * A program to check the existence and correctness of the copyright notice on a given set of
 * sources. Sources are defined to be those under management by Mercurial/Git and various options
 * are available to control the set of sources that are scanned.
 *
 * A standard set of source types are supported (see {@link CopyrightHandler#copyrightFiles}), and
 * the expected copyright for that type is passed in via the {@code --copyright-dir} option. It is
 * possible to provide a custom "overrides" file via the {@code --custom-copyright-dir} option. The
 * file should contain a list of lines of the form "pathname,copyright" where pathname indicates the
 * file with the non-standard copyright and copyright gives the custom copyright text, which must
 * reside in the directory containing the overrides file. The text "no.copyright" says that the
 * given file should not be checked at all.
 *
 * In the default mode all files known to the vc system are scanned, which can be a length operation
 * as dateinfo has to be retrieved for each file from the vc system. The {@code --modified} option
 * restricts checks to just those files that are modified. The {@code --list-dir} option avoids the
 * vc system completely and does a recursive direct scan to get the list of files.
 */
public class CheckCopyright {

    static class YearInfo {

        final int firstYear;
        final int lastYear;

        YearInfo(int firstYear, int lastYear) {
            this.firstYear = firstYear;
            this.lastYear = lastYear;
        }

        @Override
        public boolean equals(Object other) {
            if (!(other instanceof YearInfo)) {
                return false;
            }
            final YearInfo yearInfo = (YearInfo) other;
            return yearInfo.firstYear == firstYear && yearInfo.lastYear == lastYear;
        }

        @Override
        public int hashCode() {
            return firstYear ^ lastYear;
        }
    }

    static class Info extends YearInfo {

        final String fileName;

        Info(String fileName, int firstYear, int lastYear) {
            super(firstYear, lastYear);
            this.fileName = fileName;
        }

        @Override
        public String toString() {
            return fileName + " " + firstYear + ", " + lastYear;
        }
    }

    private abstract static class CopyrightHandler {
        enum CommentType {
            STAR,
            HASH
        }

        private static Map<String, CopyrightHandler> copyrightMap;
        private static String copyrightFiles = ".*/makefile|.*/Makefile|.*/CMakeLists\\.txt|.*\\.cmake|.*\\.sh|.*\\.bash|.*\\.mk|.*\\.java|.*\\.c|.*\\.cpp|.*\\.h|.*\\.hpp|.*\\.py|.*\\.g|.*\\.r";
        private static Pattern copyrightFilePattern;

        protected final String suffix;
        private CopyrightHandler customHandler;

        CopyrightHandler(CommentType commentType) {
            this.suffix = commentType.name().toLowerCase();
            initCopyrightMap();
        }

        void addCustomhandler(CopyrightHandler copyrightHandler) {
            this.customHandler = copyrightHandler;
        }

        /**
         * Add @code extension to files handled by this {@code CopyrightKind}.
         */
        protected void updateMap(String extension) {
            copyrightMap.put(extension, this);
        }

        static void addCopyrightFilesPattern(String pattern) {
            copyrightFiles += "|" + pattern;
        }

        protected abstract void readCopyrights() throws IOException;

        protected abstract RegexCopyrightConfig getRegexCopyright(String fileName) throws IOException;

        protected abstract CopyrightConfig getPlainCopyright(String fileName) throws IOException;

        protected abstract boolean handlesFile(String fileName);

        /**
         * Checks that the Oracle copyright year info was correct.
         *
         * @return {@code false} if the year info was incorrect and was not fixed otherwise return
         *         {@code true}
         * @throws IOException
         */
        protected abstract boolean checkYearInfo(String fileName, String fileContent, Matcher matcher, Info info) throws IOException;

        static String getCopyrightText(String fileName) throws IOException {
            return getCopyrightHandler(fileName).getPlainCopyright(fileName).copyright;
        }

        private static CopyrightHandler getCopyrightHandler(String fileName) {
            initCopyrightMap();
            if (!copyrightFilePattern.matcher(fileName).matches()) {
                return null;
            }
            CopyrightHandler ck = getDefaultHandler(fileName);
            if (ck.customHandler != null && ck.customHandler.handlesFile(fileName)) {
                return ck.customHandler;
            } else {
                return ck;
            }
        }

        private static void initCopyrightMap() {
            if (copyrightMap == null) {
                copyrightMap = new HashMap<>();
                copyrightFilePattern = Pattern.compile(copyrightFiles);
            }
        }

        static CopyrightHandler getDefaultHandler(String fileNameArg) {
            String fileName = fileNameArg;
            int index = fileName.lastIndexOf(File.separatorChar);
            if (index > 0) {
                fileName = fileName.substring(index + 1);
            }
            String ext = "";
            index = fileName.lastIndexOf('.');
            if (index > 0) {
                ext = fileName.substring(index + 1);
            }
            if (fileName.equals("makefile")) {
                ext = "mk";
            } else if (fileName.equals("CMakeLists.txt")) {
                ext = "cmake";
            }
            CopyrightHandler ck = copyrightMap.get(ext);
            assert ck != null : fileName;
            return ck;
        }

        protected String readCopyright(InputStream is) throws IOException {
            byte[] b = new byte[16384];
            int n = is.read(b);
            is.close();
            return new String(b, 0, n);
        }

    }

    private static class DefaultCopyrightHandler extends CopyrightHandler {
        private static final String ORACLE_COPYRIGHT = "oracle.copyright";
        private static final String ORACLE_COPYRIGHT_REGEX = "oracle.copyright.regex";

        CopyrightConfig plainCopyright;
        RegexCopyrightConfig regexCopyright;

        DefaultCopyrightHandler(CopyrightHandler.CommentType commentType) throws IOException {
            super(commentType);
            if (commentType == CopyrightHandler.CommentType.STAR) {
                updateMap("java");
                updateMap("c");
                updateMap("cpp");
                updateMap("h");
                updateMap("hpp");
                updateMap("g");
            } else {
                updateMap("r");
                updateMap("R");
                updateMap("py");
                updateMap("sh");
                updateMap("mk");
                updateMap("bash");
                updateMap("cmake");
                updateMap("");
            }
            readCopyrights();
        }

        private CopyrightConfig readCopyright(String name, boolean isRegex) throws IOException {
            String copyRightDir = COPYRIGHT_DIR.getValue();
            String fileName = "copyrights/" + name + "." + suffix;
            String copyrightPath;
            if (copyRightDir != null) {
                // try to find the default copyright first in the custom copyright directory
                File file = new File(new File(copyRightDir), fileName);
                String customCopyDir = CUSTOM_COPYRIGHT_DIR.getValue();
                if (customCopyDir != null) {
                    File cfile = new File(new File(customCopyDir), name + "." + suffix);
                    if (cfile.exists()) {
                        file = cfile;
                    }
                }
                copyrightPath = file.getAbsolutePath();
            } else {
                URL url = CheckCopyright.class.getResource(fileName);
                try {
                    copyrightPath = url.toURI().getPath();
                } catch (URISyntaxException ex) {
                    throw new IOException(ex);
                }
            }
            InputStream is = new FileInputStream(copyrightPath);
            String copyright = readCopyright(is);
            return isRegex ? new RegexCopyrightConfig(copyright, copyrightPath) : new CopyrightConfig(copyright, copyrightPath);
        }

        @Override
        protected void readCopyrights() throws IOException {
            plainCopyright = readCopyright(ORACLE_COPYRIGHT, false);
            regexCopyright = (RegexCopyrightConfig) readCopyright(ORACLE_COPYRIGHT_REGEX, true);
        }

        @Override
        protected RegexCopyrightConfig getRegexCopyright(String fileName) {
            return regexCopyright;
        }

        @Override
        protected CopyrightConfig getPlainCopyright(String fileName) {
            return plainCopyright;
        }

        @Override
        protected boolean handlesFile(String fileName) {
            return true;
        }

        static class LazyHeader {
            static {
                System.out.printf("<year in copyright> != <year last modified> -> <current year>: <file>%n");
            }

            static void emit() {

            }
        }

        /**
         * Check the year info against the copyright header. N.B. In the case of multiple matching
         * groups, only the last group is checked. I.e., only the last lines containing year info is
         * checked/updated.
         */
        @Override
        protected boolean checkYearInfo(String fileName, String fileContent, Matcher matcher, Info info) throws IOException {
            int yearInCopyright;
            int yearInCopyrightIndex;
            int groupCount = matcher.groupCount();
            if (groupCount == 0) {
                /*
                 * No group in copyright regex means there should be no year.
                 */
                return true;
            }

            String yearInCopyrightString = matcher.group(groupCount);
            yearInCopyright = Integer.parseInt(yearInCopyrightString);
            yearInCopyrightIndex = matcher.start(groupCount);
            if (yearInCopyright < info.lastYear || currentYear < yearInCopyright) {
                if (FIX.getValue()) {
                    // Use currentYear as that is what it will be when it's checked in!
                    LazyHeader.emit();
                    System.out.printf("%d != %d -> %d [fixed]: %s%n", yearInCopyright, info.lastYear, currentYear, fileName);
                    /*
                     * If the previous copyright only specified a single (initial) year, we convert
                     * it to the pair form
                     */
                    String newContent = fileContent.substring(0, yearInCopyrightIndex);
                    if (matcher.group(groupCount - 1) == null) {
                        // single year form
                        newContent += yearInCopyrightString + ", ";
                    }
                    newContent += currentYear + fileContent.substring(yearInCopyrightIndex + 4);
                    final FileOutputStream os = new FileOutputStream(fileName);
                    os.write(newContent.getBytes());
                    os.close();
                    return true;
                } else {
                    LazyHeader.emit();
                    System.out.printf("%d != %d -> %d: %s%n", yearInCopyright, info.lastYear, currentYear, fileName);
                    return false;
                }
            }
            return true;
        }

    }

    private static class CustomCopyrightHandler extends CopyrightHandler {
        private Map<String, String> overrides = new HashMap<>();
        private CopyrightHandler defaultHandler;

        CustomCopyrightHandler(CopyrightHandler.CommentType commentType, CopyrightHandler defaultHandler) {
            super(commentType);
            this.defaultHandler = defaultHandler;
        }

        void addFile(String fileName, String copyright) {
            overrides.put(fileName, copyright);
        }

        @Override
        protected void readCopyrights() throws IOException {
        }

        @Override
        protected RegexCopyrightConfig getRegexCopyright(String fileName) throws IOException {
            String override = overrides.get(fileName);
            assert override != null : fileName;
            String copyrightPath = override + "." + suffix + ".regex";
            try (InputStream fs = new FileInputStream(copyrightPath)) {
                String copyright = readCopyright(fs);
                return new RegexCopyrightConfig(copyright, copyrightPath);
            }
        }

        @Override
        protected CopyrightConfig getPlainCopyright(String fileName) throws IOException {
            String override = overrides.get(fileName);
            assert override != null : fileName;
            String copyrightPath = override + "." + suffix;
            try (InputStream fs = new FileInputStream(copyrightPath)) {
                String copyright = readCopyright(fs);
                return new CopyrightConfig(copyright, copyrightPath);
            }
        }

        @Override
        protected boolean handlesFile(String fileName) {
            return overrides.get(fileName) != null;
        }

        @Override
        protected boolean checkYearInfo(String fileName, String fileContent, Matcher matcher, Info info) throws IOException {
            // This is a bit tacky
            String copyright = overrides.get(fileName);
            if (copyright.endsWith("no.copyright")) {
                return true;
            }
            return defaultHandler.checkYearInfo(fileName, fileContent, matcher, info);
        }
    }

    private static class CopyrightConfig {
        final String copyright;
        /**
         * The location from which {@link #copyright} came.
         */
        final String origin;

        CopyrightConfig(String copyright, String origin) {
            this.copyright = copyright;
            this.origin = origin;
        }

    }

    private static class RegexCopyrightConfig extends CopyrightConfig {
        final Pattern pattern;

        RegexCopyrightConfig(String copyright, String origin) {
            super(copyright, origin);
            this.pattern = Pattern.compile(copyright, Pattern.DOTALL);
        }

    }

    private static void initCopyrightKinds() throws IOException {
        CopyrightHandler starHandler = new DefaultCopyrightHandler(CopyrightHandler.CommentType.STAR);
        CopyrightHandler hashHandler = new DefaultCopyrightHandler(CopyrightHandler.CommentType.HASH);

        String customCopyrightDir = CUSTOM_COPYRIGHT_DIR.getValue();
        if (customCopyrightDir != null) {
            CustomCopyrightHandler customStarHandler = new CustomCopyrightHandler(CopyrightHandler.CommentType.STAR, starHandler);
            CustomCopyrightHandler customHashHandler = new CustomCopyrightHandler(CopyrightHandler.CommentType.HASH, hashHandler);
            starHandler.addCustomhandler(customStarHandler);
            hashHandler.addCustomhandler(customHashHandler);

            File overrides = new File(new File(customCopyrightDir), "overrides");
            if (overrides.exists()) {
                ArrayList<String> lines = new ArrayList<>();
                boolean changed = false;
                try (BufferedReader br = new BufferedReader(new FileReader(
                                overrides))) {
                    int lineNo = 1;
                    while (true) {
                        String line = br.readLine();
                        if (line == null) {
                            break;
                        }
                        if (line.length() == 0 || line.startsWith("#")) {
                            lines.add(line);
                            continue;
                        }
                        // filename,copyright-file
                        String[] parts = line.split(",");
                        if (parts.length != 2) {
                            System.err.printf("%s:%d: override pattern must be <filename>,<copyright-file>%n%s%n", overrides.getAbsolutePath(), lineNo, line);
                            System.exit(1);
                        }

                        CopyrightHandler defaultHandler = CopyrightHandler.getDefaultHandler(parts[0]);
                        if (defaultHandler == null) {
                            System.err.println("no default copyright handler for: " + parts[0]);
                            System.exit(1);
                        }
                        if (!new File(parts[0]).exists()) {
                            System.err.printf("file %s in overrides file does not exist", parts[0]);
                            if (FIX.getValue()) {
                                System.err.print(" - removing");
                                line = null;
                                changed = true;
                            }
                            System.err.println();
                        }
                        if (line != null) {
                            lines.add(line);
                        }
                        CustomCopyrightHandler customhandler = (CustomCopyrightHandler) defaultHandler.customHandler;
                        customhandler.addFile(parts[0], new File(new File(customCopyrightDir), parts[1]).getAbsolutePath());
                        lineNo++;
                    }
                }
                if (changed) {
                    try (BufferedWriter bw = new BufferedWriter(new FileWriter(
                                    overrides))) {
                        for (String line : lines) {
                            bw.write(line);
                            bw.write('\n');
                        }
                    }
                }
            }
        }
    }

    private static final int currentYear = Calendar.getInstance().get(Calendar.YEAR);
    private static final Options options = new Options();
    private static final Option<Boolean> help = Options.newBooleanOption("help", false, "Show help message and exit.");
    private static final Option<String> COPYRIGHT_DIR = Options.newStringOption("copyright-dir", null, "override default location of copyright files");
    private static final Option<List<String>> FILES_TO_CHECK = Options.newStringListOption("files", null, "list of files to check");
    private static final Option<String> FILE_LIST = Options.newStringOption("file-list", null, "file containing list of files to check");
    private static final Option<Boolean> DIR_WALK = Options.newBooleanOption("list-dir", false, "check all files in directory tree requiring a copyright (ls -R)");
    private static final Option<Boolean> VC_ALL = Options.newBooleanOption("all", false, "check all vc managed files requiring a copyright");
    private static final Option<Boolean> VC_MODIFIED = Options.newBooleanOption("modified", false, "check all modified vc managed files requiring a copyright");
    private static final Option<Boolean> VC_EXHAUSTIVE = Options.newBooleanOption("vc", false, "check all vc managed files, irrespective of type");
    private static final Option<List<String>> PROJECT = Options.newStringListOption("projects", null, "filter files to specific projects");
    private static final Option<Boolean> FIX = Options.newBooleanOption("fix", false, "fix all possible copyright errors");
    private static final Option<String> FILE_PATTERN = Options.newStringOption("file-pattern", null, "append additional file patterns for copyright checks");
    private static final Option<Boolean> REPORT_ERRORS = Options.newBooleanOption("report-errors", false, "report non-fatal errors");
    private static final Option<Boolean> HALT_ON_ERROR = Options.newBooleanOption("halt-on-error", false, "continue after normally fatal error");
    private static final Option<Boolean> VERBOSE = Options.newBooleanOption("verbose", false, "verbose output");
    private static final Option<Boolean> VERY_VERBOSE = Options.newBooleanOption("very-verbose", false, "very verbose output");
    private static final Option<String> CUSTOM_COPYRIGHT_DIR = Options.newStringOption("custom-copyright-dir", null, "file containing filenames with custom copyrights");

    private static final String CANNOT_FOLLOW_FILE = "abort: cannot follow";
    private static volatile boolean error;
    private static boolean verbose;
    private static boolean veryVerbose;
    private static VC vc;

    private abstract static class VC {
        static boolean findInPath(String entry) {
            File dir = new File(".").getAbsoluteFile();
            while (dir != null) {
                if (new File(dir, entry).exists()) {
                    return true;
                }
                dir = dir.getParentFile();
            }
            return false;
        }

        static VC create() {
            if (findInPath(".git")) {
                vc = new Git();
            } else if (findInPath(".hg")) {
                vc = new Hg();
            } else {
                System.err.println("wd contains neither a git nor an hg repository");
                System.exit(-1);
            }
            return vc;
        }

        abstract String name();

        abstract List<String> log(String fileName) throws Exception;

        abstract List<String> getFiles(boolean all) throws Exception;

        abstract Info getInfo(String fileName, List<String> logInfo);

        protected static int getYear(String dateLine) {
            final String[] parts = dateLine.split(" ");
            assert parts[parts.length - 2].startsWith("20");
            return Integer.parseInt(parts[parts.length - 2]);
        }

    }

    private static class Hg extends VC {
        private static final String hgPath = "hg";

        @Override
        String name() {
            return hgPath;
        }

        @Override
        List<String> log(String fileName) throws Exception {
            final String[] cmd = new String[]{hgPath, "log", "-f", fileName};
            return exec(null, cmd, true);
        }

        @Override
        List<String> getFiles(boolean all) throws Exception {
            final String[] cmd;
            if (VC_MODIFIED.getValue()) {
                cmd = new String[]{hgPath, "status"};
            } else {
                cmd = new String[]{hgPath, "status", "--all"};
            }
            List<String> output = exec(null, cmd, true);
            final List<String> result = new ArrayList<>(output.size());
            for (String s : output) {
                final char ch = s.charAt(0);
                if (!(ch == 'R' || ch == 'I' || ch == '?' || ch == '!')) {
                    result.add(s.substring(2));
                }
            }
            return result;
        }

        @Override
        Info getInfo(String fileName, List<String> logInfo) {
            // process sequence of changesets
            int lastYear = 0;
            int firstYear = 0;
            int ix = 0;

            while (ix < logInfo.size()) {
                Map<String, String> tagMap = new HashMap<>();
                ix = getChangeset(logInfo, ix, tagMap);
                String date = tagMap.get("date");
                assert date != null;
                final int csYear = getYear(date);
                if (lastYear == 0) {
                    lastYear = csYear;
                    firstYear = lastYear;
                } else {
                    firstYear = csYear;
                }
                // we only want the last modified year, quit now
                break;
            }

            if (VC_MODIFIED.getValue()) {
                // We are only looking at modified and, therefore, uncommitted files.
                // This means that the lastYear value will be the current year once the
                // file is committed, so that is what we want to check against.
                lastYear = currentYear;
            }
            return new Info(fileName, firstYear, lastYear);
        }

        /**
         * Process all the changeset data, storing in {@outMap}. Return updated value of {@code ix}.
         */
        private static int getChangeset(List<String> logInfo, int ixx, Map<String, String> outMap) {
            int ix = ixx;
            String s = logInfo.get(ix++);
            while (s.length() > 0) {
                int cx = s.indexOf(':');
                String tag = s.substring(0, cx);
                String value = s.substring(cx + 1);
                outMap.put(tag, value);
                s = logInfo.get(ix++);
            }
            return ix;
        }

    }

    private static class Git extends VC {
        private static final String gitPath = "git";

        @Override
        String name() {
            return gitPath;
        }

        @Override
        List<String> log(String fileName) throws Exception {
            final String[] cmd = new String[]{gitPath, "log", "-n", "1", fileName};
            return exec(null, cmd, true);
        }

        @Override
        List<String> getFiles(boolean all) throws Exception {
            final String[] cmd;
            if (VC_MODIFIED.getValue()) {
                cmd = new String[]{gitPath, "ls-files", "-m"};
            } else {
                cmd = new String[]{gitPath, "ls-files", "-c", "-m", "-o", "--exclude-from=.gitignore"};
            }
            return exec(null, cmd, true);
        }

        @Override
        Info getInfo(String fileName, List<String> logInfo) {
            for (String line : logInfo) {
                if (line.startsWith("Date:")) {
                    int lastYear = getYear(line);
                    return new Info(fileName, -1, lastYear);
                }
            }
            assert false;
            return null;
        }

    }

    public static void main(String[] args) {
        // parse the arguments
        options.parseArguments(args);
        if (help.getValue()) {
            options.printHelp();
            return;
        }

        vc = VC.create();

        verbose = VERBOSE.getValue();
        veryVerbose = VERY_VERBOSE.getValue();

        if (FILE_PATTERN.getValue() != null) {
            CopyrightHandler.addCopyrightFilesPattern(FILE_PATTERN.getValue());
        }

        try {
            initCopyrightKinds();
            List<String> filesToCheck = null;
            if (VC_ALL.getValue()) {
                filesToCheck = vc.getFiles(true);
            } else if (VC_MODIFIED.getValue()) {
                filesToCheck = vc.getFiles(false);
            } else if (FILE_LIST.getValue() != null) {
                filesToCheck = readFileList(FILE_LIST.getValue());
            } else if (DIR_WALK.getValue()) {
                filesToCheck = getDirWalkFiles();
            } else if (FILES_TO_CHECK.getValue() != null) {
                filesToCheck = FILES_TO_CHECK.getValue();
            } else {
                // no option set, default to ALL
                filesToCheck = vc.getFiles(true);
            }
            if (filesToCheck != null && !filesToCheck.isEmpty()) {
                processFiles(filesToCheck);
            } else {
                System.out.println("nothing to check");
            }
            System.exit(error ? 1 : 0);
        } catch (Exception ex) {
            System.err.println("processing failed: " + ex);
            ex.printStackTrace();
        }
    }

    private static void processFiles(List<String> fileNames) throws Exception {
        final List<String> projects = PROJECT.getValue();
        Calendar cal = Calendar.getInstance();

        int threadCount = Runtime.getRuntime().availableProcessors();

        ThreadPoolExecutor threadPool = new ThreadPoolExecutor(threadCount, threadCount, 0L, TimeUnit.MILLISECONDS, new LinkedBlockingQueue<>());
        try {
            List<Future<?>> tasks = new ArrayList<>();

            for (String fileName : fileNames) {
                if (projects == null || isInProjects(fileName, projects)) {
                    File file = new File(fileName);
                    if (file.isDirectory()) {
                        continue;
                    }
                    tasks.add(threadPool.submit(() -> processFile(cal, fileName)));
                }
            }

            for (Future<?> task : tasks) {
                task.get();
            }
        } finally {
            threadPool.shutdown();
        }
    }

    private static void processFile(Calendar cal, String fileName) {
        try {
            if (verbose) {
                System.out.println("checking " + fileName);
            }
            Info info;
            if (DIR_WALK.getValue() || FILE_LIST.getValue() != null) {
                info = getFromLastModified(cal, fileName);
            } else {
                final List<String> logInfo = vc.log(fileName);
                if (logInfo.isEmpty()) {
                    // an added file, so go with last modified
                    info = getFromLastModified(cal, fileName);
                } else {
                    info = vc.getInfo(fileName, logInfo);
                }
            }
            checkFile(info);
        } catch (Exception e) {
            System.err.format("COPYRIGHT CHECK WARNING: error while processing %s: %s%n", fileName, e.getMessage());
        }
    }

    private static Info getFromLastModified(Calendar cal, String fileName) {
        File file = new File(fileName);
        cal.setTimeInMillis(file.lastModified());
        int year = cal.get(Calendar.YEAR);
        return new Info(fileName, year, year);
    }

    private static boolean isInProjects(String fileName, List<String> projects) {
        final int ix = fileName.indexOf(File.separatorChar);
        if (ix < 0) {
            return false;
        }
        final String fileProject = fileName.substring(0, ix);
        for (String project : projects) {
            if (fileProject.equals(project)) {
                return true;
            }
        }
        return false;
    }

    private static List<String> readFileList(String fileListName) throws IOException {
        final List<String> result = new ArrayList<>();
        try (BufferedReader b = new BufferedReader(new FileReader(fileListName))) {
            while (true) {
                final String fileName = b.readLine();
                if (fileName == null) {
                    break;
                }
                if (fileName.isEmpty()) {
                    continue;
                }
                result.add(fileName);
            }
        }
        return result;
    }

    private static String getFileContent(byte[] fileContentBytes) {
        String fileContent = new String(fileContentBytes);
        if (fileContent.isEmpty() || fileContent.charAt(fileContent.length() - 1) != '\n') {
            /*
             * If the file does not end with a newline, the DOTALL does not work. Although files
             * should have a trailing newline, it is not the copyright checkers job to ensure this.
             */
            return fileContent + '\n';
        }
        return fileContent;
    }

    private static void checkFile(Info info) throws IOException {
        String fileName = info.fileName;
        File file = new File(fileName);
        if (!file.exists()) {
            System.err.println("COPYRIGHT CHECK WARNING: file " + file + " doesn't exist");
            return;
        }
        int fileLength = (int) file.length();
        byte[] fileContentBytes = new byte[fileLength];
        FileInputStream is = new FileInputStream(file);
        is.read(fileContentBytes);
        is.close();
        final String fileContent = getFileContent(fileContentBytes);
        CopyrightHandler copyrightHandler = CopyrightHandler.getCopyrightHandler(fileName);
        if (copyrightHandler != null) {
            RegexCopyrightConfig copyright = copyrightHandler.getRegexCopyright(fileName);
            Matcher copyrightMatcher = copyright.pattern.matcher(fileContent);
            if (copyrightMatcher.matches()) {
                if (!copyrightHandler.checkYearInfo(fileName, fileContent, copyrightMatcher, info)) {
                    error = true;
                }
            } else {
                /*
                 * If copyright is missing, insert it, otherwise user has to manually fix existing
                 * copyright.
                 */
                if (!fileContent.contains("Copyright")) {
                    System.out.print("file " + fileName + " has missing copyright");
                    if (FIX.getValue()) {
                        final FileOutputStream os = new FileOutputStream(file);
                        os.write(CopyrightHandler.getCopyrightText(fileName).getBytes());
                        os.write(fileContentBytes);
                        os.close();
                        System.out.println("...fixed");
                    } else {
                        System.out.println();
                        error = true;
                    }
                } else {
                    System.out.println(fileName + " has a copyright that does not match the regex in " + copyright.origin + (FIX.getValue() ? " [could not fix]" : ""));
                    error = true;
                }
            }
        } else if (VC_EXHAUSTIVE.getValue()) {
            System.out.println("ERROR: file " + fileName + " has no copyright");
            error = true;
        }
    }

    private static List<String> getDirWalkFiles() {
        File cwd = new File(System.getProperty("user.dir"));
        ArrayList<String> result = new ArrayList<>();
        getDirWalkFiles(cwd, result);
        // remove "user.dir" prefix to make files relative as per hg
        String cwdPath = cwd.getAbsolutePath() + '/';
        for (int i = 0; i < result.size(); i++) {
            String path = result.get(i);
            result.set(i, path.replace(cwdPath, ""));
        }
        return result;
    }

    private static void getDirWalkFiles(File dir, ArrayList<String> list) {
        File[] files = dir.listFiles();
        if (files != null) {
            for (File file : files) {
                if (ignoreFile(file.getName())) {
                    continue;
                }
                if (file.isDirectory()) {
                    getDirWalkFiles(file, list);
                } else {
                    list.add(file.getAbsolutePath());
                }
            }
        } else {
            System.out.println("ERROR: Cannot read directory " + dir);
            error = true;
        }
    }

    private static final String IGNORE_LIST = "\\.hg|\\.git|.*\\.class|bin|src_gen";
    private static final Pattern ignorePattern = Pattern.compile(IGNORE_LIST);

    private static boolean ignoreFile(String name) {
        return ignorePattern.matcher(name).matches();
    }

    private static List<String> exec(File workingDir, String[] command, boolean failOnError) throws IOException, InterruptedException {
        List<String> result = new ArrayList<>();
        if (veryVerbose) {
            System.out.println("Executing process in directory: " + workingDir);
            for (String c : command) {
                System.out.println("  " + c);
            }
        }
        final Process process = Runtime.getRuntime().exec(command, null, workingDir);
        try {
            result = readOutput(process.getInputStream());
            final int exitValue = process.waitFor();
            if (exitValue != 0) {
                final List<String> errorResult = readOutput(process.getErrorStream());
                if (REPORT_ERRORS.getValue()) {
                    System.err.print("execution of command: ");
                    for (String c : command) {
                        System.err.print(c);
                        System.err.print(' ');
                    }
                    System.err.println("failed with result " + exitValue);
                    for (String e : errorResult) {
                        System.err.println(e);
                    }
                }
                if (failOnError && HALT_ON_ERROR.getValue()) {
                    if (!cannotFollowNonExistentFile(errorResult)) {
                        throw new Error("terminating");
                    }
                }
            }
        } finally {
            process.destroy();
        }
        return result;
    }

    private static boolean cannotFollowNonExistentFile(List<String> errorResult) {
        return errorResult.size() == 1 && errorResult.get(0).startsWith(CANNOT_FOLLOW_FILE);
    }

    private static List<String> readOutput(InputStream is) throws IOException {
        final List<String> result = new ArrayList<>();
        BufferedReader bs = null;
        try {
            bs = new BufferedReader(new InputStreamReader(is));
            while (true) {
                final String line = bs.readLine();
                if (line == null) {
                    break;
                }
                result.add(line);
            }
        } finally {
            if (bs != null) {
                bs.close();
            }
        }
        return result;
    }

    private static class Options {
        private static Map<String, Option<?>> optionMap = new TreeMap<>();

        private static Option<Boolean> newBooleanOption(String name, boolean defaultValue, String helpArg) {
            Option<Boolean> option = new Option<>(name, helpArg, defaultValue, false, false);
            optionMap.put(key(name), option);
            return option;
        }

        private static Option<String> newStringOption(String name, String defaultValue, String helpArg) {
            Option<String> option = new Option<>(name, helpArg, defaultValue);
            optionMap.put(key(name), option);
            return option;
        }

        private static Option<List<String>> newStringListOption(String name, List<String> defaultValue, String helpArg) {
            Option<List<String>> option = new Option<>(name, helpArg, defaultValue, true, true);
            optionMap.put(key(name), option);
            return option;
        }

        private static String key(String name) {
            return "--" + name;
        }

        void parseArguments(String[] args) {
            int i = 0;
            while (i < args.length) {
                final String arg = args[i];
                if (arg.startsWith("--")) {
                    Option<?> option = optionMap.get(arg);
                    if (option == null || (option.consumesNext() && i == args.length - 1)) {
                        System.out.println("usage:");
                        printHelp();
                        System.exit(1);
                    }
                    if (option.consumesNext()) {
                        i++;
                        option.setValue(args[i]);
                    } else {
                        option.setValue(true);
                    }
                }
                i++;
            }
        }

        void printHelp() {
            int maxKeyLen = 0;
            for (Map.Entry<String, Option<?>> entrySet : optionMap.entrySet()) {
                int l = entrySet.getKey().length();
                if (l > maxKeyLen) {
                    maxKeyLen = l;
                }
            }
            for (Map.Entry<String, Option<?>> entrySet : optionMap.entrySet()) {
                String key = entrySet.getKey();
                System.out.printf("  %s", key);
                for (int i = 0; i < maxKeyLen - key.length(); i++) {
                    System.out.print(' ');
                }
                System.out.printf("   %s%n", entrySet.getValue().help);
            }
        }
    }

    private static class Option<T> {
        private final String name;
        private final String help;
        private final boolean consumesNext;
        private final boolean isList;
        private T value;

        Option(String name, String help, T defaultValue, boolean consumesNext, boolean isList) {
            this.name = name;
            this.help = help;
            this.value = defaultValue;
            this.consumesNext = consumesNext;
            this.isList = isList;

        }

        Option(String name, String help, T defaultValue) {
            this(name, help, defaultValue, true, false);
        }

        T getValue() {
            return value;
        }

        boolean consumesNext() {
            return consumesNext;
        }

        @SuppressWarnings("unchecked")
        void setValue(boolean value) {
            this.value = (T) Boolean.valueOf(value);
        }

        @SuppressWarnings("unchecked")
        void setValue(String value) {
            if (isList) {
                String[] parts = value.split(",");
                this.value = (T) Arrays.asList(parts);
            } else {
                this.value = (T) value;
            }
        }

        @SuppressWarnings("unused")
        String getName() {
            return name;
        }
    }

}
